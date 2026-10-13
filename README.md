# Codex Windows kit

A native PowerShell companion to Heini's `codex-arch-kit`, prepared
13 October 2026. Preview first, apply deliberately, and restore from verified
backups. The repository includes editable templates, meaningful local tests and
a GitHub Actions workflow for Windows and Linux.

## Requirements

- PowerShell **7.4 or newer**, invoked as `pwsh`.
- Python **3.11 or newer**, plus the pinned dependency in `requirements.txt`.
- Codex CLI for validation and apply. Offline preview can omit it.
- WinGet only when using `-InstallTools` or `-Bootstrap`.

The standalone Codex installation requires no Node.js, npm or fnm. Existing
Node/fnm, prompt tools, Micromamba and PowerShell profile content are retained.
Configuration defaults to `$env:CODEX_HOME`, or `$HOME\.codex` when it is unset.

OpenAI recommends Windows 11. Fully updated Windows 10 is supported on a
best-effort basis; its documented minimum for ConPTY is build 1809.
[Windows support and sandbox documentation][windows]

## Quick start

Extract the ZIP and open a terminal inside `codex-windows-kit`. If necessary,
install PowerShell 7 from your existing Windows PowerShell terminal:

```powershell
winget install --id Microsoft.PowerShell --exact --source winget
pwsh
```

Read the templates, then install missing Git/ripgrep/Python, Codex and the TOML
dependency, and apply the configuration:

```powershell
pwsh -NoProfile -ExecutionPolicy Bypass -File .\setup-codex-windows.ps1 `
  -Apply -Bootstrap
```

`Bypass` applies only to that process. The kit does not change persistent
execution policy. WinGet and Codex's sandbox provisioning can request UAC.
Run subsequent Codex work from an ordinary, unelevated terminal.

If Python and Codex already exist, omit package and CLI installation:

```powershell
pwsh -NoProfile -File .\setup-codex-windows.ps1 `
  -Apply -InstallDependencies
```

This creates `.venv` and installs `tomlkit==0.13.3`; it also applies the kit.
To prepare dependencies and inspect a preview before your first apply, instead
run these commands:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
pwsh -NoProfile -File .\setup-codex-windows.ps1 -Output .\preview-one
```

Use `py -3` in place of `python` if that is your Python launcher. Preview does
not install software or modify the target home/profile. Every preview directory
must be new. After reviewing the files and `manifest.json`, rerun with `-Apply`
and another output directory. Apply re-renders and revalidates the current state;
it does not blindly copy an older preview.

An offline preview is also available after installing Python/tomlkit:

```powershell
pwsh -NoProfile -File .\setup-codex-windows.ps1 `
  -SkipCliValidation -Effort ultra -Output .\offline-preview
```

Offline previews cannot apply or generate completion. With `-Effort auto`, an
offline preview explicitly falls back to `xhigh`.

## Sign in and inspect the effective settings

Open a new terminal, then start Codex from your project directory:

```powershell
codex login
codex
```

In a new chat, inspect `/model`, `/status`, `/debug-config`, `/memories` and
`/agent`. Model/effort availability depends on your account and client. CLI
arguments, project settings and managed requirements can override personal
defaults. Existing chats can retain earlier settings.

The kit chooses the highest supported level from the CLI's bundled catalogue.
For Astra on the tested CLI that is `ultra`. This confirms catalogue/parser
support, not account entitlement or a successful inference. Specify another
available model or effort explicitly when needed:

```powershell
pwsh -NoProfile -File .\setup-codex-windows.ps1 `
  -Apply -Model gpt-6-astra -Effort max
```

## Installed defaults

| Setting | Default |
| --- | --- |
| Model | GPT-6 Astra, matching the Linux kit |
| Reasoning and Plan mode | Highest advertised level; explicit override allowed |
| Permissions | Workspace writes; approvals on request |
| Legacy Windows sandbox | `elevated` |
| Shell networking | Disabled within workspace sandbox |
| Web search | Live |
| Credential store | OS keyring |
| Local memories | Generation and use enabled |
| Concurrent subagents | Four, in addition to the primary |
| Docs MCP | Public OpenAI documentation server |

MXC is optional via `-PreferMxc`, with the legacy implementation retained as a
fallback. It requires compatible Windows capabilities. For a legacy setup that
cannot provision the elevated sandbox, `-WindowsSandbox unelevated` is available;
it has weaker isolation. The installer configures these choices; Codex performs
any sandbox provisioning when needed. See the [official sandbox guide][windows].

The four standalone agents are `repo_mapper`, `script_engineer`, `repo_reviewer`
and `statistics_reviewer`. Their definitions are inherited from the Linux kit.
The first, third and fourth request read-only sandboxes; the script engineer
requests workspace writes. They do not pin another model or reasoning effort.
Existing `[agents]` defaults, explicit spawn choices and runtime policy still
apply. Delegation follows your request or applicable project instructions.

Memories are separate from curated `AGENTS.md` instructions and from browser
ChatGPT memory. Enabling them does not import Linux/browser histories. Required
project rules belong in a repository `AGENTS.md`.

## Optional completion and your existing profile

Profile editing is opt-in. This appends a small managed loader block and backs
up the complete original file. Your existing Titus/Starship/fnm configuration
is retained. To use a Titus custom file that your host profile already loads:

```powershell
pwsh -NoProfile -File .\setup-codex-windows.ps1 `
  -Apply -EnableCompletion `
  -ProfileFile "$HOME\Documents\PowerShell\CTTcustom.ps1"
```

Without `-ProfileFile`, `-EnableCompletion` uses the current user's current-host
profile. Restart that PowerShell host after installing. The completion loader
contains the exact installed path, including a custom `-CodexHome`.

## Backups and restore

Changed files are backed up under
`$CODEX_HOME\windows-kit-backups\<UTC timestamp>` with original-byte checksums,
installed-byte checksums and a destination manifest. On a normal failed write,
the configuration transaction rolls back. Repeating an identical apply performs
no configuration/profile writes and creates no additional backup.

Preview restoration, then apply it:

```powershell
pwsh -NoProfile -File .\setup-codex-windows.ps1 -Restore latest
pwsh -NoProfile -File .\setup-codex-windows.ps1 -Restore latest -Apply
```

Give the same `-CodexHome` for a custom home. If the transaction changed a shell
profile, also supply its original `-ProfileFile` on both restore commands.
`-Restore` also accepts one explicit backup directory. Latest restore walks
back one applied transaction at a time. Restored/rolled-back entries are skipped.

Restore refuses newer edits, checksum mismatches and destinations outside its
managed scope. After reviewing newer edits, `-ForceRestore` explicitly allows
overwriting them. Preserve any wanted edits before using that option.

Restore covers configuration files and an opted-in profile. CLI/packages,
authentication, generated memory/history, preview directories and empty folders
are retained. Backups preserve bytes and POSIX modes; they are not Windows ACL
or whole-machine snapshots. A pending manifest records an interrupted apply;
restore permits files matching either its before or after checksum. Inspect a
stale `.windows-kit.lock` before removing it and attempting recovery.

The kit refuses symlinks/junctions, conflicting custom providers/default
profiles, shadowing global `AGENTS.override.md`, malformed markers and different
agents with the same names. Review an agent collision before using
`-OverwriteAgents`. Unrelated TOML settings and comments survive; configuration
output uses UTF-8, with the existing newline convention. UTF-8/UTF-16 Markdown
and profiles retain their encoding/BOM and text outside managed blocks.

## Testing and repository development

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
pwsh -NoProfile -File .\tests\Test-PowerShell.ps1
pwsh -NoProfile -File .\tests\Test-CodexIntegration.ps1 -Codex codex.exe
```

Tests use temporary homes/profiles, including Unicode, quotes and brackets in
paths. Integration starts the CLI with closed stdin for strict parsing and
disables background plugin/memory work for that process. It never creates a
model inference or signs in. An intentionally unknown setting verifies that
strict parsing actually rejects invalid configuration.

The checked-in GitHub Actions matrix runs the configuration and PowerShell
tests on `windows-latest` and `ubuntu-latest`; it installs only the TOML
dependency. Real-CLI integration is a separate local command. See
[the test report](docs/TEST_REPORT.md) for what was actually run here.

To begin your own repository after extraction:

```powershell
git init -b main
git add .
git commit -m "Add tested Windows Codex starter"
```

No GitHub repository or remote is created by the installer. Review generated
previews/backups before sharing: they can contain existing private settings.
The default `.preview`, `.venv` and common generated files are ignored by Git.
An arbitrary `-Output` directory is your responsibility to exclude.

## Layout and reference

| Path | Purpose |
| --- | --- |
| `setup-codex-windows.ps1` | PowerShell entry point and opt-in installations |
| `configure.py` | TOML merge, strict CLI validation, transactions and restore |
| `config.toml` | Editable personal baseline |
| `personal-instructions.md` | Managed portion of global `AGENTS.md` |
| `agents/*.toml` | Four standalone agent definitions |
| `scripts/Test-Completion.ps1` | Syntax check without running completion |
| `tests/` | Unit, wrapper and real-CLI integration tests |
| `.github/workflows/test.yml` | Windows/Linux CI |

Use `-Help`, `-LongHelp` or `Get-Help .\setup-codex-windows.ps1 -Full` for
parameter details. Configuration semantics were checked against the
[official configuration reference][config] and an installed Codex CLI.
Installation uses the [official Windows CLI installer][cli].

[windows]: https://learn.chatgpt.com/docs/windows/windows-sandbox
[config]: https://learn.chatgpt.com/docs/config-file/config-reference
[cli]: https://learn.chatgpt.com/docs/codex/cli
