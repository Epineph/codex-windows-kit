# Verification report

Prepared 13 October 2026. All listed executed checks passed on the final
implementation. The test environment was Linux x86_64, Python 3.12.14,
PowerShell 7.6.6, tomlkit 0.13.3 and Codex CLI 0.159.2.

## Executed checks

| Suite | Result | Evidence scope |
| --- | --- | --- |
| Python unittest | 30 passed | Merge, backups, rollback, conflicts and restore |
| PowerShell harness | 13 passed | Syntax, help, arguments and offline preview |
| CLI integration | 17 passed | Wrapper, strict parse, apply and completion |

These comprise **60 passing checks**, without native Windows execution.
Additional Python syntax, TOML, agent-field, YAML structure and authored
81-column checks also passed. No model inference or sign-in was performed.

### Configuration and transaction tests

- A preview leaves the target home unchanged or absent.
- TOML comments, unrelated tables, multiline arrays and CRLF survive the merge.
- Personal instructions and profiles retain surrounding text, Unicode and
  UTF-16 encoding/BOM; quote-containing paths are escaped correctly.
- Malformed TOML, ambiguous markers, custom-provider/default-profile conflicts,
  shadowing instructions and existing different agents fail before installation.
- Repeated identical applies cause no file writes or additional backups.
- Original bytes and POSIX modes survive apply/restore; authentication files
  remain untouched, and newly created managed files are removed by restore.
- Injected failures after replacement recover the original files. Injected
  restore failures recover the installed state.
- Newer edits, stale plans, active locks, modified backup bytes, unsafe manifest
  destinations and symlink destinations are rejected.
- A concurrent edit between restore writes is preserved; earlier restore writes
  roll back. Pending transactions can restore matching before/after states.
- Catalogue selection, offline fallback and explicit-effort forwarding work.
  Offline apply is refused.

### PowerShell and real-CLI tests

- All five PowerShell scripts parse with the PowerShell language parser.
- Help works, invalid effort fails and bootstrap cannot install during preview.
- Native argument arrays handle spaces, apostrophes, Unicode and brackets.
- The real CLI validates a staged configuration. Astra's bundled catalogue
  selects Ultra. This is parser/catalogue evidence, not account-access evidence.
- A temporary home receives four standalone agents and the personal baseline.
- Generated completion parses, loads through a staged profile and expands
  `codex --mo` to `--model`.
- The real wrapper repeats apply without another backup and previews restore
  before applying it. Original configuration/profile content is recovered.
- An intentionally unknown configuration key fails strict parsing and creates
  no installation transaction.

The CLI's `features` subcommand does not support `--strict-config`. Validation
therefore uses the supported `app-server` runtime command with closed stdin,
an isolated home and background plugin/memory work disabled for that process.
It exits without creating a chat. Catalogue lookup uses `--bundled`.

## Not executed

- Native Windows package or standalone Codex installation.
- Windows sandbox provisioning or sandboxed command execution/network isolation.
- Windows Credential Manager sign-in/storage or existing account entitlement.
- The Windows-only junction check; it is included in the PowerShell harness.
- GitHub Actions runs. The Windows/Linux workflow is supplied and structurally
  checked, but has not run on GitHub.
- Live OpenAI documentation MCP connectivity or a model inference.

The kit was not installed into a real user profile or Codex home during tests.
The test report does not certify native Windows installation/sandbox behavior.

## Reproduction

From the extracted repository, with dependencies available:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
pwsh -NoProfile -File .\tests\Test-PowerShell.ps1
pwsh -NoProfile -File .\tests\Test-CodexIntegration.ps1 -Codex codex.exe
```

On Linux use `python3` for unittest and an explicit `-Codex` path if needed.
All test homes/profiles are temporary. Package installation and login are not
part of these commands. The GitHub Actions matrix runs the first two suites.
