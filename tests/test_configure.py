"""Behavioral tests: temporary homes only, with no inference or installs."""

from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import configure as kit


class ConfigurationTests(unittest.TestCase):
  def setUp(self):
    self.directory = tempfile.TemporaryDirectory(prefix="kit O'Brien ü-")
    self.root = Path(self.directory.name)
    self.home = self.root / 'home'
    self.home.mkdir()
    self.output = StringIO()
    self.redirect = redirect_stdout(self.output)
    self.redirect.__enter__()

  def tearDown(self):
    self.redirect.__exit__(None, None, None)
    self.directory.cleanup()

  def plan(self, **kwargs):
    return kit.build_plan(self.home, effort='ultra', **kwargs)

  def install(self):
    files = self.plan()
    return kit.apply_files(files, self.home)

  def test_preview_does_not_modify_home(self):
    files = self.plan()
    kit.save_preview(files, self.root / 'preview', self.home)
    self.assertEqual(list(self.home.iterdir()), [])
    config = tomllib.loads((self.root / 'preview/config.toml').read_text())
    self.assertEqual(config['model'], 'gpt-6-astra')
    self.assertEqual(config['windows']['sandbox'], 'elevated')
    self.assertEqual(config['cli_auth_credentials_store'], 'keyring')
    self.assertEqual(config['agents']['max_concurrent_threads_per_session'], 4)

  def test_comments_custom_tables_and_windows_newlines_survive(self):
    path = self.home / 'config.toml'
    path.write_bytes(
      b'# My settings\r\nmodel = "old" # Keep this comment\r\n'
      b'[mcp_servers.local]\r\ncommand = "python"\r\n'
      b'args = [\r\n  "server.py", # multi-line\r\n]\r\n'
      b'[agents]\r\nmax_threads = 2\r\n'
    )
    kit.apply_files(self.plan(), self.home)
    rendered = path.read_bytes()
    parsed = tomllib.loads(rendered.decode())
    self.assertIn(b'# Keep this comment', rendered)
    self.assertIn(b'# multi-line', rendered)
    self.assertEqual(parsed['mcp_servers']['local']['args'], ['server.py'])
    self.assertNotIn('max_threads', parsed['agents'])
    self.assertNotIn(b'\n', rendered.replace(b'\r\n', b''))

  def test_marked_text_preserves_surrounding_content_exactly(self):
    text = 'head  \r\n\r\n' + kit.BEGIN + '\r\nold\r\n' + kit.END
    text += '\r\ntail  \r\n'
    replaced = kit.marked(text, 'new\nbody')
    self.assertTrue(replaced.startswith('head  \r\n\r\n'))
    self.assertTrue(replaced.endswith('\r\ntail  \r\n'))
    self.assertEqual(replaced, kit.marked(replaced, 'new\nbody'))

  def test_markers_in_prose_do_not_count_as_block_markers(self):
    text = 'The marker is ' + kit.BEGIN + ' in this sentence.\n'
    self.assertTrue(kit.marked(text, 'body').startswith(text))

  def test_ambiguous_markers_fail(self):
    for text in (kit.BEGIN, kit.END + '\n' + kit.BEGIN,
                 kit.BEGIN + '\n' + kit.BEGIN + '\n' + kit.END):
      with self.subTest(text=text), self.assertRaises(ValueError):
        kit.marked(text, 'body')

  def test_unicode_utf16_instructions_preserve_encoding(self):
    path = self.home / 'AGENTS.md'
    path.write_bytes('Prior instructions: æøå\r\n'.encode('utf-16'))
    kit.apply_files(self.plan(), self.home)
    current = path.read_bytes()
    self.assertTrue(current.startswith(b'\xff\xfe'))
    self.assertTrue(current.decode('utf-16').startswith(
      'Prior instructions: æøå\r\n',
    ))

  def test_invalid_toml_fails_before_writing(self):
    path = self.home / 'config.toml'
    path.write_text('broken = [', encoding='utf-8')
    with self.assertRaises(Exception):
      self.plan()
    self.assertEqual(path.read_text(), 'broken = [')
    self.assertFalse((self.home / kit.BACKUPS).exists())

  def test_table_scalar_conflict_fails(self):
    (self.home / 'config.toml').write_text('features = false\n')
    with self.assertRaisesRegex(ValueError, 'table into scalar'):
      self.plan()

  def test_custom_provider_and_default_profile_need_review(self):
    for text in ('model_provider = "private"\n', 'profile = "work"\n'):
      (self.home / 'config.toml').write_text(text)
      with self.assertRaises(ValueError):
        self.plan()

  def test_override_instructions_fail_instead_of_silently_shadowing(self):
    (self.home / 'AGENTS.override.md').write_text('other instructions')
    with self.assertRaisesRegex(ValueError, 'shadow'):
      self.plan()

  def test_existing_different_agent_is_not_overwritten(self):
    directory = self.home / 'agents'
    directory.mkdir()
    agent = directory / 'repo_mapper.toml'
    agent.write_text('name = "mine"\n')
    with self.assertRaisesRegex(ValueError, 'Different agent'):
      self.plan()
    self.assertEqual(agent.read_text(), 'name = "mine"\n')
    kit.apply_files(self.plan(overwrite_agents=True), self.home)
    self.assertEqual(tomllib.loads(agent.read_text())['name'], 'repo_mapper')

  def test_repeated_apply_has_no_writes_or_new_backups(self):
    backup = self.install()
    snapshots = {
      p: p.stat().st_mtime_ns for p in self.home.rglob('*') if p.is_file()
    }
    with patch.object(kit, 'write_atomic', side_effect=AssertionError('write')):
      self.assertIsNone(kit.apply_files(self.plan(), self.home))
    self.assertEqual(snapshots, {
      p: p.stat().st_mtime_ns for p in self.home.rglob('*') if p.is_file()
    })
    self.assertEqual(kit.latest_backup(self.home), backup)

  def test_backup_and_restore_preserve_original_bytes_and_auth(self):
    config = self.home / 'config.toml'
    original = b'\xef\xbb\xbf# old config\r\nmodel = "before"\r\n'
    config.write_bytes(original)
    auth = self.home / 'auth.json'
    auth.write_bytes(b'unchanged test fixture')
    backup = self.install()
    kit.restore_files(backup, self.home, apply=True)
    self.assertEqual(config.read_bytes(), original)
    self.assertEqual(auth.read_bytes(), b'unchanged test fixture')
    self.assertFalse((self.home / 'AGENTS.md').exists())
    self.assertFalse((self.home / 'agents/repo_mapper.toml').exists())
    self.assertEqual(json.loads((backup / 'manifest.json').read_text())['state'],
                     'restored')

  def test_restore_preview_is_read_only(self):
    backup = self.install()
    before = (self.home / 'config.toml').read_bytes()
    kit.restore_files(backup, self.home)
    self.assertEqual((self.home / 'config.toml').read_bytes(), before)
    self.assertEqual(json.loads((backup / 'manifest.json').read_text())['state'],
                     'applied')

  def test_newer_edit_blocks_restore_before_any_mutation(self):
    backup = self.install()
    path = self.home / 'AGENTS.md'
    path.write_text('newer manual edit')
    config = (self.home / 'config.toml').read_bytes()
    with self.assertRaisesRegex(ValueError, 'Newer edit'):
      kit.restore_files(backup, self.home, apply=True)
    self.assertEqual((self.home / 'config.toml').read_bytes(), config)
    self.assertEqual(path.read_text(), 'newer manual edit')
    kit.restore_files(backup, self.home, apply=True, force=True)
    self.assertFalse(path.exists())

  def test_modified_backup_fails_checksum(self):
    (self.home / 'config.toml').write_text('model = "before"\n')
    backup = self.install()
    (backup / '000.before').write_text('tampered')
    with self.assertRaisesRegex(ValueError, 'checksum mismatch'):
      kit.restore_files(backup, self.home, apply=True)

  def test_manifest_cannot_restore_an_unrelated_path(self):
    backup = self.install()
    path = backup / 'manifest.json'
    data = json.loads(path.read_text())
    data['files'][0]['path'] = str(self.root / 'outside.txt')
    path.write_text(json.dumps(data))
    with self.assertRaisesRegex(ValueError, 'Unsafe destination'):
      kit.restore_files(backup, self.home, apply=True)
    self.assertFalse((self.root / 'outside.txt').exists())

  def test_stale_plan_aborts_before_installation(self):
    files = self.plan()
    (self.home / 'config.toml').write_text('model = "newer"\n')
    with self.assertRaisesRegex(ValueError, 'changed since planning'):
      kit.apply_files(files, self.home)
    self.assertFalse((self.home / 'AGENTS.md').exists())

  def test_apply_failure_after_replacement_rolls_back(self):
    original = b'model = "before"\r\n'
    (self.home / 'config.toml').write_bytes(original)
    calls = 0

    def fail_after_replace(path, content, mode):
      nonlocal calls
      kit.write_atomic(path, content, mode)
      calls += 1
      if calls == 2:
        raise OSError('injected failure after replace')

    with self.assertRaisesRegex(OSError, 'injected'):
      kit.apply_files(self.plan(), self.home, writer=fail_after_replace)
    self.assertEqual((self.home / 'config.toml').read_bytes(), original)
    self.assertFalse((self.home / 'AGENTS.md').exists())
    self.assertFalse((self.home / '.windows-kit.lock').exists())
    state = next((self.home / kit.BACKUPS).glob('*/manifest.json'))
    self.assertEqual(json.loads(state.read_text())['state'], 'rolled-back')

  def test_restore_failure_keeps_installed_bytes(self):
    (self.home / 'config.toml').write_text('model = "before"\n')
    (self.home / 'AGENTS.md').write_text('before instructions')
    backup = self.install()
    before = {p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
    calls = 0

    def fail_on_second(path, content, mode):
      nonlocal calls
      calls += 1
      if calls == 2:
        raise OSError('injected restore failure')
      kit.write_atomic(path, content, mode)

    with self.assertRaises(OSError):
      kit.restore_files(backup, self.home, apply=True, writer=fail_on_second)
    self.assertEqual(before, {
      p: p.read_bytes() for p in self.home.rglob('*') if p.is_file()
    })

  def test_pending_transaction_can_restore_unwritten_originals(self):
    original = b'model = "before"\n'
    (self.home / 'config.toml').write_bytes(original)
    backup = self.install()
    path = backup / 'manifest.json'
    manifest = json.loads(path.read_text())
    manifest['state'] = 'pending'
    path.write_text(json.dumps(manifest))
    (self.home / 'config.toml').write_bytes(original)
    kit.restore_files(backup, self.home, apply=True)
    self.assertEqual((self.home / 'config.toml').read_bytes(), original)

  def test_restore_detects_a_concurrent_edit_between_writes(self):
    (self.home / 'config.toml').write_text('model = "before"\n')
    backup = self.install()
    installed = (self.home / 'config.toml').read_bytes()

    def modify_later_destination(path, content, mode):
      kit.write_atomic(path, content, mode)
      (self.home / 'AGENTS.md').write_text('concurrent edit')

    with self.assertRaisesRegex(ValueError, 'during restoration'):
      kit.restore_files(backup, self.home, apply=True,
                        writer=modify_later_destination)
    self.assertEqual((self.home / 'config.toml').read_bytes(), installed)
    self.assertEqual((self.home / 'AGENTS.md').read_text(), 'concurrent edit')

  def test_existing_lock_blocks_changes(self):
    (self.home / '.windows-kit.lock').write_text('pid=test')
    with self.assertRaisesRegex(ValueError, 'stale lock'):
      kit.apply_files(self.plan(), self.home)
    self.assertFalse((self.home / 'config.toml').exists())

  def test_symlink_destination_is_rejected(self):
    target = self.root / 'target'
    target.write_text('do not touch')
    try:
      (self.home / 'config.toml').symlink_to(target)
    except OSError:
      self.skipTest('host does not permit symlink creation')
    with self.assertRaisesRegex(ValueError, 'link or reparse'):
      self.plan()
    self.assertEqual(target.read_text(), 'do not touch')

  @unittest.skipIf(os.name == 'nt', 'POSIX file-mode test')
  def test_existing_file_mode_survives_apply_and_restore(self):
    path = self.home / 'config.toml'
    path.write_text('model = "before"\n')
    path.chmod(0o640)
    backup = self.install()
    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)
    kit.restore_files(backup, self.home, apply=True)
    self.assertEqual(stat.S_IMODE(path.stat().st_mode), 0o640)

  def test_preview_output_guard_and_no_overwrite(self):
    files = self.plan()
    for output in (self.home, self.root, self.home / 'preview', kit.ROOT):
      with self.assertRaises(ValueError):
        kit.save_preview(files, output, self.home)
    output = self.root / 'preview'
    kit.save_preview(files, output, self.home)
    with self.assertRaises(FileExistsError):
      kit.save_preview(files, output, self.home)

  def test_offline_apply_is_rejected(self):
    with redirect_stderr(StringIO()), self.assertRaises(SystemExit) as error:
      kit.main([
        '--apply', '--skip-cli-validation', '--codex-home', str(self.home),
      ])
    self.assertEqual(error.exception.code, 2)
    self.assertEqual(list(self.home.iterdir()), [])

  def test_catalogue_selection_and_explicit_effort(self):
    result = subprocess.CompletedProcess([], 0, stdout=json.dumps({'models': [{
      'slug': 'gpt-6-astra',
      'supported_reasoning_levels': [{'effort': 'max'}, {'effort': 'ultra'}],
    }]}), stderr='')
    with patch.object(kit, 'run_codex', return_value=result):
      selected = kit.select_effort('codex', self.home, 'gpt-6-astra')
      self.assertEqual(selected, 'ultra')
    result = subprocess.CompletedProcess([], 1, stdout='', stderr='offline')
    with patch.object(kit, 'run_codex', return_value=result):
      selected = kit.select_effort('codex', self.home, 'gpt-6-astra')
      self.assertEqual(selected, 'xhigh')

  def test_cli_rejection_does_not_touch_home(self):
    result = subprocess.CompletedProcess([], 1, stdout='', stderr='bad config')
    with patch.object(kit, 'run_codex', return_value=result):
      with self.assertRaisesRegex(ValueError, 'bad config'):
        self.plan(cli='codex')
    self.assertEqual(list(self.home.iterdir()), [])

  def test_profile_escaping_encoding_and_explicit_restore_path(self):
    profile = self.root / "O'Brien ü [profile].ps1"
    original = '# Titus profile\r\n$unchanged = "æøå"\r\n'.encode('utf-16')
    profile.write_bytes(original)
    with patch.object(kit, 'validate_candidate', return_value=(
        'ultra', b'# mock completion\n')):
      files = self.plan(cli='codex', powershell='pwsh', enable_completion=True,
                        profile_file=profile)
    profile_content = files[-1].content.decode('utf-16')
    self.assertIn("O''Brien", profile_content)
    self.assertTrue(profile_content.startswith(original.decode('utf-16')))
    backup = kit.apply_files(files, self.home)
    with self.assertRaisesRegex(ValueError, 'requires its --profile-file'):
      kit.restore_files(backup, self.home, apply=True)
    kit.restore_files(backup, self.home, profile_file=profile, apply=True)
    self.assertEqual(profile.read_bytes(), original)


if __name__ == '__main__':
  unittest.main()
