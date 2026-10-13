#!/usr/bin/env python3
"""Preview, install or restore Heini's Codex configuration.

Windows users should run setup-codex-windows.ps1. This helper is portable so
the transaction behavior can also be tested on Linux, entirely in temp homes.
Requires Python 3.11+ and the dependency in requirements.txt.
"""

from __future__ import annotations

import argparse
from collections.abc import MutableMapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import subprocess
import tempfile
import tomllib

import tomlkit

ROOT = Path(__file__).resolve().parent
BEGIN = "# BEGIN HEINI CODEX WINDOWS KIT"
END = "# END HEINI CODEX WINDOWS KIT"
PROFILE_BEGIN = "# BEGIN CODEX WINDOWS KIT COMPLETION"
PROFILE_END = "# END CODEX WINDOWS KIT COMPLETION"
BACKUPS = "windows-kit-backups"
EFFORTS = ("ultra", "max", "xhigh", "high", "medium", "low")


# --- Files and text -----------------------------------------------------------

def absolute(path):
  """Normalize paths without following links or junctions."""
  return Path(os.path.abspath(Path(path).expanduser()))


def digest(data):
  return hashlib.sha256(data).hexdigest() if data is not None else None


def assert_safe_path(path):
  """Reject symlinks, Windows reparse points and non-file destinations."""
  path = absolute(path)
  for item in (path, *path.parents):
    try:
      info = item.lstat()
    except FileNotFoundError:
      continue
    attributes = getattr(info, "st_file_attributes", 0)
    reparse = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 1024)
    if stat.S_ISLNK(info.st_mode) or attributes & reparse:
      raise ValueError(f"Refusing link or reparse point: {item}")
    if item == path and not stat.S_ISREG(info.st_mode):
      raise ValueError(f"Expected a regular file destination: {path}")
    if item != path and not stat.S_ISDIR(info.st_mode):
      raise ValueError(f"Expected a directory: {item}")


def read_bytes(path):
  assert_safe_path(path)
  return path.read_bytes() if path.exists() else None


def decode_text(data):
  """Retain BOM/encoding for Markdown and PowerShell profile text."""
  data = data or b""
  if data.startswith((b"\xff\xfe", b"\xfe\xff")):
    encoding = "utf-16-le" if data.startswith(b"\xff\xfe") else "utf-16-be"
    return data[2:].decode(encoding), encoding, data[:2]
  bom = b"\xef\xbb\xbf" if data.startswith(b"\xef\xbb\xbf") else b""
  return data[len(bom):].decode("utf-8"), "utf-8", bom


def newline_of(text):
  return "\r\n" if "\r\n" in text else "\n"


def with_newlines(text, newline):
  return text.replace("\r\n", "\n").replace("\n", newline)


def marked(text, body, begin=BEGIN, end=END):
  """Update exactly one whole-line block; preserve text outside it."""
  newline = newline_of(text)
  block = begin + newline + with_newlines(body.rstrip(), newline)
  block += newline + end
  starts = list(re.finditer(rf"(?m)^{re.escape(begin)}\r?$", text))
  stops = list(re.finditer(rf"(?m)^{re.escape(end)}\r?$", text))
  if starts or stops:
    if len(starts) != 1 or len(stops) != 1:
      raise ValueError("Ambiguous managed markers; repair before rerunning.")
    if stops[0].start() < starts[0].start():
      raise ValueError("Managed block end occurs before its beginning.")
    # Leave the existing line ending following the end marker in place.
    stop = stops[0].start() + len(end)
    return text[:starts[0].start()] + block + text[stop:]
  separator = "" if not text else newline if text.endswith("\n") else newline * 2
  return text + separator + block + newline


def merge(target, source, prefix=""):
  """Replace managed leaves, retaining unrelated keys and TOML comments."""
  for key, value in source.items():
    location = f"{prefix}.{key}" if prefix else key
    if isinstance(value, MutableMapping):
      if key not in target:
        target[key] = tomlkit.table()
      if not isinstance(target[key], MutableMapping):
        raise ValueError(f"Cannot merge table into scalar: {location}")
      merge(target[key], value, location)
    else:
      if key in target and isinstance(target[key], MutableMapping):
        raise ValueError(f"Cannot replace table with scalar: {location}")
      target[key] = value


@dataclass(frozen=True)
class Change:
  path: Path
  content: bytes
  before: bytes | None
  relative: str
  kind: str = "home"


def change(path, content, relative, kind="home"):
  return Change(absolute(path), content, read_bytes(path), relative, kind)


# --- Local Codex validation: no model inference -------------------------------

def run_codex(cli, arguments, home):
  """Use argument lists and an isolated Codex home, never a shell string."""
  command = [str(cli), *arguments]
  if os.name == "nt" and Path(cli).suffix.lower() == ".ps1":
    raise ValueError("Use codex.exe or codex.cmd, not the npm PowerShell shim.")
  return subprocess.run(
    command, env=dict(os.environ, CODEX_HOME=str(home)), cwd=home,
    stdin=subprocess.DEVNULL, capture_output=True, text=True,
    encoding="utf-8", errors="replace", timeout=45, check=False,
  )


def select_effort(cli, home, model):
  """Choose an advertised level; catalogue data does not prove entitlement."""
  try:
    result = run_codex(cli, ["debug", "models", "--bundled"], home)
    if result.returncode:
      raise ValueError("catalogue command failed")
    data = json.loads(result.stdout)
    models = data if isinstance(data, list) else data.get("models", [])
    for entry in models:
      if entry.get("slug", entry.get("id")) != model:
        continue
      levels = entry.get("supported_reasoning_levels", [])
      available = {
        item if isinstance(item, str) else item.get("effort") for item in levels
      }
      return next(level for level in EFFORTS if level in available)
    raise ValueError("model absent from catalogue")
  except (ValueError, TypeError, StopIteration, subprocess.TimeoutExpired):
    print("Catalogue unavailable; selecting xhigh. Verify access in /model.")
    return "xhigh"


def validate_candidate(config, files, cli, requested_effort, powershell=None):
  """Parse a staged candidate strictly, without modifying the real home."""
  with tempfile.TemporaryDirectory(prefix="codex-kit-check-") as temporary:
    home = Path(temporary)
    for item in files:
      if item.relative.startswith("agents/"):
        target = home / item.relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(item.content)
    effort = requested_effort
    if effort == "auto":
      effort = select_effort(cli, home, str(config["model"]))
    config["model_reasoning_effort"] = effort
    config["plan_mode_reasoning_effort"] = effort
    (home / "config.toml").write_text(tomlkit.dumps(config), encoding="utf-8")
    # Runtime commands support strict parsing. Close app-server's stdin at
    # startup: it validates configuration then exits without creating a chat.
    # Disable background plugin/memory work only in this validation process.
    result = run_codex(cli, [
      "--strict-config", "--disable", "remote_plugin", "--disable", "memories",
      "app-server",
    ], home)
    if result.returncode:
      detail = result.stderr.strip() or result.stdout.strip()
      raise ValueError(
        f"Codex rejected candidate; update CLI or fix it:\n{detail}",
      )
    completion = None
    if powershell:
      result = run_codex(cli, ["completion", "powershell"], home)
      if result.returncode or not result.stdout.strip():
        raise ValueError("Could not generate PowerShell completion.")
      completion = result.stdout.encode("utf-8")
      candidate = home / "completion.ps1"
      candidate.write_bytes(completion)
      check = subprocess.run(
        [str(powershell), "-NoProfile", "-File",
         str(ROOT / "scripts" / "Test-Completion.ps1"), "-Path", str(candidate)],
        capture_output=True, text=True, encoding="utf-8", timeout=30,
        check=False,
      )
      if check.returncode:
        raise ValueError("Generated completion failed PowerShell syntax check.")
    return effort, completion


# --- Planning and preview ----------------------------------------------------

def build_plan(home, *, model="gpt-6-astra", effort="auto", cli=None,
               sandbox="elevated", enable_completion=False, profile_file=None,
               powershell=None, overwrite_agents=False, prefer_mxc=False):
  home = absolute(home)
  config_path = home / "config.toml"
  original = read_bytes(config_path) or b""
  text = original.decode("utf-8-sig")
  config = tomlkit.parse(text)
  if config.get("model_provider", "openai") != "openai":
    raise ValueError("Existing custom model_provider needs manual review.")
  if config.get("profile"):
    raise ValueError("Existing default profile needs manual review.")
  override = read_bytes(home / "AGENTS.override.md")
  if override and override.strip():
    raise ValueError(
      "AGENTS.override.md would shadow the installed instructions.",
    )
  desired = tomlkit.parse((ROOT / "config.toml").read_text(encoding="utf-8"))
  desired["model"] = model
  desired["windows"]["sandbox"] = sandbox
  if prefer_mxc:
    desired["features"]["prefer_mxc"] = True
  merge(config, desired)
  # This legacy alias is owned by the concurrency setting above.
  config["agents"].pop("max_threads", None)
  files = []
  for source in sorted((ROOT / "agents").glob("*.toml")):
    content = source.read_bytes()
    tomllib.loads(content.decode("utf-8"))
    item = change(home / "agents" / source.name, content,
                  f"agents/{source.name}")
    conflict = item.before is not None and item.before != content
    if conflict and not overwrite_agents:
      raise ValueError(f"Different agent exists: {item.path}; review before "
                       "using --overwrite-agents.")
    files.append(item)
  if enable_completion and (not cli or not powershell or not profile_file):
    raise ValueError("Completion needs Codex, PowerShell and --profile-file.")
  if cli:
    selected, completion = validate_candidate(
      config, files, cli, effort, powershell if enable_completion else None,
    )
  else:
    selected = "xhigh" if effort == "auto" else effort
    completion = None
    config["model_reasoning_effort"] = selected
    config["plan_mode_reasoning_effort"] = selected
    print("OFFLINE PREVIEW: not validated by Codex; cannot apply this preview.")
  rendered = with_newlines(tomlkit.dumps(config), newline_of(text))
  tomllib.loads(rendered)
  files.insert(0, change(config_path, rendered.encode("utf-8"), "config.toml"))
  instructions_path = home / "AGENTS.md"
  instructions, encoding, bom = decode_text(read_bytes(instructions_path))
  body = (ROOT / "personal-instructions.md").read_text(encoding="utf-8")
  merged = marked(instructions, body)
  files.insert(1, change(instructions_path, bom + merged.encode(encoding),
                         "AGENTS.md"))
  if enable_completion:
    completion_path = home / "completion.powershell.ps1"
    files.append(change(completion_path, completion, completion_path.name))
    profile_file = absolute(profile_file)
    if profile_file.is_relative_to(home) or profile_file == config_path:
      raise ValueError("PowerShell profile must be outside the Codex home.")
    existing, encoding, bom = decode_text(read_bytes(profile_file))
    quoted = str(completion_path).replace("'", "''")
    loader = f"if (Test-Path -LiteralPath '{quoted}') {{\n  . '{quoted}'\n}}"
    merged = marked(existing, loader, PROFILE_BEGIN, PROFILE_END)
    files.append(change(profile_file, bom + merged.encode(encoding),
                        "profile.ps1", "profile"))
  paths = [item.path for item in files]
  if len(paths) != len(set(paths)):
    raise ValueError("Multiple writes to the same destination are not allowed.")
  print(f"Model: {model}; reasoning: {selected}; CLI validation: {bool(cli)}")
  return files


def save_preview(files, output, home):
  """Create a new candidate directory; never overwrite a previous preview."""
  output, home = absolute(output), absolute(home)
  if (output == ROOT or output in ROOT.parents or output.is_relative_to(home)
      or home.is_relative_to(output)):
    raise ValueError("Choose a separate, new preview directory.")
  assert_safe_path(output / "manifest.json")
  output.mkdir(parents=True, exist_ok=False)
  manifest = []
  for item in files:
    target = output / item.relative
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(item.content)
    manifest.append({
      "destination": str(item.path), "candidate": item.relative,
      "changed": item.before != item.content,
      "before_sha256": digest(item.before), "after_sha256": digest(item.content),
    })
  (output / "manifest.json").write_text(
    json.dumps(manifest, indent=2) + "\n", encoding="utf-8",
  )
  print(f"Preview: {output}")


# --- Transactional writes and restoration ------------------------------------

def write_atomic(path, content, mode=0o600):
  path.parent.mkdir(parents=True, exist_ok=True)
  descriptor, name = tempfile.mkstemp(prefix=".codex-kit-", dir=path.parent)
  temporary = Path(name)
  try:
    with os.fdopen(descriptor, "wb") as stream:
      stream.write(content)
      stream.flush()
      os.fsync(stream.fileno())
    os.chmod(temporary, mode)
    os.replace(temporary, path)
  finally:
    temporary.unlink(missing_ok=True)


@contextmanager
def transaction_lock(home):
  """Serialize applies/restores; a stale lock requires manual inspection."""
  home.mkdir(parents=True, exist_ok=True)
  lock = home / ".windows-kit.lock"
  assert_safe_path(lock)
  try:
    descriptor = os.open(lock, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
  except FileExistsError as error:
    raise ValueError(
      f"Another transaction or stale lock exists: {lock}",
    ) from error
  try:
    with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
      stream.write(f"pid={os.getpid()}\n")
    yield
  finally:
    lock.unlink()


def write_manifest(backup, manifest):
  data = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
  write_atomic(backup / "manifest.json", data)


def apply_files(files, home, writer=write_atomic):
  """Back up changed files, verify snapshots and undo failed writes."""
  files = [item for item in files if item.before != item.content]
  if not files:
    print("Already configured; no writes or additional backup.")
    return None
  home = absolute(home)
  with transaction_lock(home):
    for item in files:
      if read_bytes(item.path) != item.before:
        raise ValueError(f"File changed since planning: {item.path}")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    backup = home / BACKUPS / stamp
    assert_safe_path(backup / "manifest.json")
    backup.mkdir(parents=True, mode=0o700)
    manifest = {"format": 1, "home": str(home), "state": "pending", "files": []}
    for index, item in enumerate(files):
      mode = 0o600
      if item.before is not None:
        mode = stat.S_IMODE(item.path.stat().st_mode)
      copy = f"{index:03d}.before"
      if item.before is not None:
        write_atomic(backup / copy, item.before)
      manifest["files"].append({
        "path": str(item.path), "kind": item.kind, "copy": copy,
        "before_sha256": digest(item.before),
        "after_sha256": digest(item.content),
        "existed": item.before is not None, "mode": mode,
      })
    write_manifest(backup, manifest)
    attempted = []
    try:
      for item, entry in zip(files, manifest["files"]):
        if read_bytes(item.path) != item.before:
          raise ValueError(f"File changed during installation: {item.path}")
        attempted.append((item, entry))
        writer(item.path, item.content, entry["mode"])
      manifest["state"] = "applied"
      write_manifest(backup, manifest)
    except BaseException as error:
      failures = []
      for item, entry in reversed(attempted):
        try:
          current = read_bytes(item.path)
          if current not in (item.before, item.content):
            raise ValueError("concurrent edit prevents safe rollback")
          if item.before is None:
            item.path.unlink(missing_ok=True)
          else:
            write_atomic(item.path, item.before, entry["mode"])
        except BaseException as failure:
          failures.append(f"{item.path}: {failure}")
      manifest["state"] = "pending" if failures else "rolled-back"
      write_manifest(backup, manifest)
      if failures:
        raise RuntimeError(f"Rollback incomplete; inspect {backup}: "
                           + "; ".join(failures)) from error
      raise
  print(f"Applied {len(files)} changed files. Backup: {backup}")
  return backup


def latest_backup(home):
  for path in sorted((home / BACKUPS).glob("*/manifest.json"), reverse=True):
    data = json.loads(read_bytes(path).decode("utf-8"))
    if data.get("state") in ("applied", "pending"):
      return path.parent
  raise ValueError("No applied or interrupted backup to restore.")


def restore_files(backup, home, *, profile_file=None, force=False,
                  apply=False, writer=write_atomic):
  """Restore one snapshot, refusing newer edits and tampered backup bytes."""
  home, backup = absolute(home), absolute(backup)
  if backup.parent != home / BACKUPS:
    raise ValueError(
      "Backup must be a direct child of this home's backup folder.",
    )
  manifest_path = backup / "manifest.json"
  manifest = json.loads(read_bytes(manifest_path).decode("utf-8"))
  if (manifest.get("format") != 1 or manifest.get("home") != str(home)
      or manifest.get("state") not in ("applied", "pending")):
    raise ValueError("Backup does not describe a restorable transaction here.")
  operations = []
  seen = set()
  allowed_profile = absolute(profile_file) if profile_file else None
  for entry in manifest["files"]:
    path = absolute(entry["path"])
    if path in seen:
      raise ValueError("Duplicate destination in backup manifest.")
    seen.add(path)
    if entry["kind"] == "profile":
      if path != allowed_profile:
        raise ValueError(
          "Restore of a shell profile requires its --profile-file.",
        )
    elif (entry["kind"] != "home" or not path.is_relative_to(home)
          or path.is_relative_to(home / BACKUPS)
          or path.relative_to(home).as_posix() not in {
            "config.toml", "AGENTS.md", "completion.powershell.ps1",
            *[f"agents/{p.name}" for p in (ROOT / "agents").glob("*.toml")],
          }):
      raise ValueError("Unsafe destination in backup manifest.")
    if not re.fullmatch(r"\d{3}\.before", entry["copy"]):
      raise ValueError("Unsafe backup filename.")
    original = read_bytes(backup / entry["copy"]) if entry["existed"] else None
    if entry["existed"] and original is None:
      raise ValueError("Original backup file is missing.")
    if digest(original) != entry["before_sha256"]:
      raise ValueError("Original backup checksum mismatch.")
    current = read_bytes(path)
    expected = {entry["after_sha256"]}
    if manifest["state"] == "pending":
      expected.add(entry["before_sha256"])
    if not force and digest(current) not in expected:
      raise ValueError(
        f"Newer edit detected: {path}; review before --force-restore.",
      )
    operations.append((path, original, current, entry["mode"]))
  print(f"Restore {'APPLY' if apply else 'PREVIEW'}: {backup}; "
        f"{len(operations)} files")
  if not apply:
    return
  with transaction_lock(home):
    for path, original, current, mode in operations:
      if read_bytes(path) != current:
        raise ValueError(f"File changed since restore planning: {path}")
    attempted = []
    try:
      for path, original, current, mode in operations:
        if read_bytes(path) != current:
          raise ValueError(f"File changed during restoration: {path}")
        attempted.append((path, original, current, mode))
        if original is None:
          path.unlink(missing_ok=True)
        else:
          writer(path, original, mode)
      manifest["state"] = "restored"
      write_manifest(backup, manifest)
    except BaseException as error:
      failures = []
      for path, original, current, mode in reversed(attempted):
        try:
          if read_bytes(path) not in (current, original):
            raise ValueError("concurrent edit prevents safe rollback")
          if current is None:
            path.unlink(missing_ok=True)
          else:
            write_atomic(path, current, mode)
        except BaseException as failure:
          failures.append(f"{path}: {failure}")
      if failures:
        raise RuntimeError("Restore rollback incomplete: "
                           + "; ".join(failures)) from error
      raise
  print("Restored original file bytes; CLI/package installations are retained.")


# --- Command-line entry point ------------------------------------------------

def main(argv=None):
  parser = argparse.ArgumentParser(description=__doc__)
  parser.add_argument("--apply", action="store_true")
  parser.add_argument("--codex-home", type=Path, default=Path(
    os.environ.get("CODEX_HOME", str(Path.home() / ".codex")),
  ))
  parser.add_argument("--output", type=Path)
  parser.add_argument("--model", default="gpt-6-astra")
  parser.add_argument("--effort", choices=("auto", *EFFORTS), default="auto")
  parser.add_argument("--windows-sandbox", choices=("elevated", "unelevated"),
                      default="elevated")
  parser.add_argument("--prefer-mxc", action="store_true")
  parser.add_argument("--codex", default=shutil.which("codex"))
  parser.add_argument("--powershell", default=shutil.which("pwsh"))
  parser.add_argument("--enable-completion", action="store_true")
  parser.add_argument("--profile-file", type=Path)
  parser.add_argument("--overwrite-agents", action="store_true")
  parser.add_argument("--skip-cli-validation", action="store_true")
  parser.add_argument(
    "--restore", help="Backup path, or 'latest'. Preview by default.",
  )
  parser.add_argument("--force-restore", action="store_true")
  args = parser.parse_args(argv)
  home = absolute(args.codex_home)
  if args.restore:
    backup = Path(args.restore)
    if args.restore == "latest":
      backup = latest_backup(home)
    restore_files(backup, home, profile_file=args.profile_file,
                  force=args.force_restore, apply=args.apply)
    return 0
  if args.force_restore:
    parser.error("--force-restore requires --restore")
  if args.apply and args.skip_cli_validation:
    parser.error("Apply requires CLI validation; offline previews cannot apply.")
  cli = None if args.skip_cli_validation else args.codex
  if not cli and not args.skip_cli_validation:
    parser.error("Codex unavailable. Install it or use --skip-cli-validation.")
  files = build_plan(
    home, model=args.model, effort=args.effort, cli=cli,
    sandbox=args.windows_sandbox, prefer_mxc=args.prefer_mxc,
    enable_completion=args.enable_completion, profile_file=args.profile_file,
    powershell=args.powershell, overwrite_agents=args.overwrite_agents,
  )
  stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
  output = args.output or ROOT / ".preview" / stamp
  save_preview(files, output, home)
  if args.apply:
    apply_files(files, home)
  else:
    print("Preview only. Rerun with --apply to install a validated candidate.")
  return 0


if __name__ == "__main__":
  try:
    raise SystemExit(main())
  except (ValueError, OSError, subprocess.SubprocessError) as error:
    raise SystemExit(f"Error: {error}") from error
