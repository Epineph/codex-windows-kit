# Codex Windows kit

Use Python 3.11+ and PowerShell 7.4+. Use two-space indentation, comment-based
PowerShell help, useful CLI examples and lines within 81 columns where practical.

The user-facing entry point is setup-codex-windows.ps1. configure.py owns TOML
merging and file transactions. config.toml and personal-instructions.md are the
editable source templates; agents/*.toml are standalone Codex custom agents.

Run `python -m unittest discover -s tests -v` after transaction or merge changes.
Run `pwsh -NoProfile -File tests/Test-PowerShell.ps1` after PowerShell changes.
Use tests' temporary homes. Never run the installer against your real Codex
home, install packages, change execution policy or sign in as part of tests.

Preserve unrelated config keys/comments and profile content. Apply requires
successful local CLI validation. Repeated identical applies must not write
files or create another backup. Fail before mutation on conflicts or unsafe
paths. Restore must reject newer edits unless explicitly forced.

Do not commit generated previews, backups, credentials or private config.
