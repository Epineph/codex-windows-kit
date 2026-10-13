#requires -Version 7.4
<#
.SYNOPSIS
  Preview, install or restore Heini's native Windows Codex configuration.
.DESCRIPTION
  Preview is the default. -Apply writes a validated configuration, personal
  instructions and four custom agents. Existing settings and comments survive.
  Changed files receive a backup and are rolled back if a write fails.

  -Bootstrap combines -InstallTools, -InstallCli and -InstallDependencies.
  Installation flags require -Apply. Package and CLI installations are separate
  from the configuration transaction and are retained after restore.

  Requires PowerShell 7.4+, Python 3.11+ and tomlkit. -InstallDependencies
  creates a repository-local .venv. No API key is required for setup or tests.
.PARAMETER Apply
  Apply configuration changes, or execute a requested restore.
.PARAMETER Bootstrap
  Install missing Git/ripgrep/Python, the Codex CLI, and Python dependencies.
.PARAMETER InstallTools
  Use WinGet for missing Git, ripgrep and Python 3.13 on Windows.
.PARAMETER InstallCli
  Run the official standalone Windows Codex installer. Does not require Node.
.PARAMETER InstallDependencies
  Create/use .venv and install the pinned TOML editing dependency.
.PARAMETER CodexHome
  Configuration target. Defaults to CODEX_HOME or the user's .codex directory.
.PARAMETER Model
  Model identifier. Defaults to gpt-6-astra, matching the Linux kit.
.PARAMETER Effort
  auto chooses the highest advertised level; otherwise use the supplied level.
.PARAMETER WindowsSandbox
  Legacy native sandbox selection, elevated by default. Codex provisions it.
.PARAMETER PreferMxc
  Prefer MXC where supported, retaining the selected legacy sandbox fallback.
.PARAMETER EnableCompletion
  Generate completion and append/update a managed block in ProfileFile.
.PARAMETER ProfileFile
  Profile to modify; defaults to the current user's current-host profile.
  Supply the same path to restore a transaction that changed a profile.
.PARAMETER Output
  New preview directory. Defaults to a timestamped directory under .preview.
.PARAMETER Codex
  Explicit path to codex.exe/codex.cmd, useful for an existing installation.
.PARAMETER OverwriteAgents
  Replace different agents with the supplied names after reviewing them.
.PARAMETER SkipCliValidation
  Create an offline preview only; cannot be combined with -Apply.
.PARAMETER Restore
  Preview restoring a backup directory, or the most recent backup with 'latest'.
.PARAMETER ForceRestore
  Permit restore over newer edits after review. Requires -Restore.
.PARAMETER Help
  Show concise usage.
.PARAMETER LongHelp
  Show full comment-based help.
.EXAMPLE
  .\setup-codex-windows.ps1 -SkipCliValidation -Output .\preview
.EXAMPLE
  .\setup-codex-windows.ps1 -Apply -Bootstrap
.EXAMPLE
  .\setup-codex-windows.ps1 -Apply -EnableCompletion `
    -ProfileFile "$HOME\Documents\PowerShell\CTTcustom.ps1"
.EXAMPLE
  .\setup-codex-windows.ps1 -Restore latest
.EXAMPLE
  .\setup-codex-windows.ps1 -Apply -Restore latest
#>
[CmdletBinding()]
param(
  [switch]$Apply,
  [switch]$Bootstrap,
  [switch]$InstallTools,
  [switch]$InstallCli,
  [switch]$InstallDependencies,
  [string]$CodexHome,
  [ValidateNotNullOrEmpty()][string]$Model = 'gpt-6-astra',
  [ValidateSet('auto', 'low', 'medium', 'high', 'xhigh', 'max', 'ultra')]
  [string]$Effort = 'auto',
  [ValidateSet('elevated', 'unelevated')]
  [string]$WindowsSandbox = 'elevated',
  [switch]$PreferMxc,
  [switch]$EnableCompletion,
  [string]$ProfileFile,
  [string]$Output,
  [string]$Codex,
  [switch]$OverwriteAgents,
  [switch]$SkipCliValidation,
  [string]$Restore,
  [switch]$ForceRestore,
  [switch]$Help,
  [switch]$LongHelp
)

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

# --- Help and argument validation --------------------------------------------

if ($Help) {
  @'
Usage: pwsh -NoProfile -File .\setup-codex-windows.ps1 [options]

  (no action flag)        Preview the configuration; requires Codex and tomlkit
  -Apply                 Install the newly validated candidate
  -Bootstrap -Apply      Install prerequisites, CLI, dependency and configuration
  -EnableCompletion      Add a managed completion block to -ProfileFile
  -CodexHome PATH        Use a different configuration home
  -Model ID -Effort LEVEL Override the Astra / automatic maximum defaults
  -SkipCliValidation     Offline preview; requires Python/tomlkit, cannot apply
  -Restore latest        Preview restoring the last applied backup
  -Restore latest -Apply Restore it; give -ProfileFile if it changed a profile
  -Help / -LongHelp      Concise / full help with examples

See README.md for dependencies, sign-in, backup scope and native Windows checks.
'@ | Write-Output
  exit 0
}
if ($LongHelp) {
  Get-Help -Name $PSCommandPath -Full
  exit 0
}

# --- Helpers -----------------------------------------------------------------

function Invoke-CheckedCommand {
  param([string]$Command, [string[]]$ArgumentList)
  & $Command @ArgumentList
  if ($LASTEXITCODE -ne 0) {
    throw "Command failed with exit code ${LASTEXITCODE}: $Command"
  }
}

function Find-PythonCommand {
  param([switch]$IgnoreVenv)
  $candidates = [System.Collections.Generic.List[object]]::new()
  if (-not $IgnoreVenv) {
    $relative = if ($IsWindows) { '.venv/Scripts/python.exe' } else {
      '.venv/bin/python'
    }
    $venvPython = Join-Path $PSScriptRoot $relative
    if (Test-Path -LiteralPath $venvPython -PathType Leaf) {
      $candidates.Add(@{ Command = $venvPython; Prefix = @() })
    }
  }
  # Prefer the active environment/PATH interpreter before the Windows launcher.
  foreach ($name in @('python', 'python3', 'py')) {
    $found = Get-Command $name -CommandType Application -All `
      -ErrorAction SilentlyContinue
    foreach ($application in $found) {
      if ($application.Source -notmatch 'WindowsApps[\\/]python') {
        $prefix = if ($name -eq 'py') { @('-3') } else { @() }
        $candidates.Add(@{ Command = $application.Source; Prefix = $prefix })
      }
    }
  }
  foreach ($candidate in $candidates) {
    $probeArgs = @($candidate.Prefix) + @(
      '-c', 'import sys; sys.exit(0 if sys.version_info >= (3,11) else 1)'
    )
    & $candidate.Command @probeArgs 2>$null
    if ($LASTEXITCODE -eq 0) {
      return [pscustomobject]$candidate
    }
  }
  throw 'Python 3.11+ was not found. Use -Apply -InstallTools or install Python.'
}

function Update-ProcessPath {
  if (-not $IsWindows) { return }
  foreach ($scope in @('Machine', 'User')) {
    $persisted = [Environment]::GetEnvironmentVariable('Path', $scope)
    foreach ($entry in ($persisted -split ';')) {
      if ($entry -and ($env:PATH -split ';') -notcontains $entry) {
        $env:PATH += ";$entry"
      }
    }
  }
}

function Install-MissingTools {
  if (-not $IsWindows) { throw '-InstallTools requires native Windows.' }
  $packages = [System.Collections.Generic.List[string]]::new()
  if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    $packages.Add('Git.Git')
  }
  if (-not (Get-Command rg -ErrorAction SilentlyContinue)) {
    $packages.Add('BurntSushi.ripgrep.MSVC')
  }
  try { $null = Find-PythonCommand -IgnoreVenv } catch {
    $packages.Add('Python.Python.3.13')
  }
  if ($packages.Count -eq 0) { return }
  $winget = Get-Command winget -ErrorAction SilentlyContinue
  if (-not $winget) {
    throw 'WinGet is missing. Install Microsoft App Installer, then rerun.'
  }
  foreach ($package in $packages) {
    Invoke-CheckedCommand $winget.Source @(
      'install', '--id', $package, '--exact', '--source', 'winget',
      '--accept-package-agreements', '--accept-source-agreements',
      '--disable-interactivity'
    )
  }
  Update-ProcessPath
}

function Install-CodexCli {
  if (-not $IsWindows) { throw '-InstallCli requires native Windows.' }
  $directory = Join-Path ([IO.Path]::GetTempPath()) (
    'codex-installer-' + [guid]::NewGuid().ToString('N')
  )
  $null = New-Item -ItemType Directory -Path $directory
  try {
    $installer = Join-Path $directory 'install.ps1'
    Invoke-WebRequest -Uri 'https://chatgpt.com/codex/install.ps1' `
      -OutFile $installer -TimeoutSec 60
    Invoke-CheckedCommand (Join-Path $PSHOME 'pwsh.exe') @(
      '-NoProfile', '-ExecutionPolicy', 'Bypass', '-File', $installer
    )
    Update-ProcessPath
  } finally {
    Remove-Item -LiteralPath $directory -Recurse -Force
  }
}

function Find-CodexCommand {
  if ($Codex) {
    $explicit = Get-Command $Codex -CommandType Application `
      -ErrorAction SilentlyContinue
    if (-not $explicit) { throw "Codex executable was not found: $Codex" }
    return $explicit.Source
  }
  if ($IsWindows -and $env:LOCALAPPDATA) {
    $standalone = Join-Path $env:LOCALAPPDATA `
      'Programs/OpenAI/Codex/bin/codex.exe'
    if (Test-Path -LiteralPath $standalone -PathType Leaf) { return $standalone }
  }
  foreach ($name in @('codex.exe', 'codex.cmd', 'codex')) {
    $found = Get-Command $name -CommandType Application `
      -ErrorAction SilentlyContinue
    if ($found) { return $found.Source }
  }
  return $null
}

# --- Installation and configuration ------------------------------------------

try {
  if ($Bootstrap) {
    $InstallTools = $true
    $InstallCli = $true
    $InstallDependencies = $true
  }
  $installRequested = $InstallTools -or $InstallCli -or $InstallDependencies
  if ($installRequested -and -not $Apply) {
    throw 'Installation flags require -Apply. Preview does not install software.'
  }
  if ($SkipCliValidation -and $Apply) {
    throw '-Apply requires CLI validation; offline previews cannot apply.'
  }
  if ($ForceRestore -and -not $Restore) {
    throw '-ForceRestore requires -Restore.'
  }
  if ($Restore -and ($InstallTools -or $InstallCli -or $InstallDependencies)) {
    throw 'Restore cannot be combined with software installation flags.'
  }
  if ($InstallTools) { Install-MissingTools }
  if ($InstallCli) { Install-CodexCli }
  if ($InstallDependencies) {
    $python = Find-PythonCommand -IgnoreVenv
    $environment = Join-Path $PSScriptRoot '.venv'
    Invoke-CheckedCommand $python.Command (@($python.Prefix) + @(
      '-m', 'venv', $environment
    ))
    $python = Find-PythonCommand
    Invoke-CheckedCommand $python.Command (@($python.Prefix) + @(
      '-m', 'pip', 'install', '--disable-pip-version-check',
      '-r', (Join-Path $PSScriptRoot 'requirements.txt')
    ))
  }
  $python = Find-PythonCommand
  $dependencyProbe = @($python.Prefix) + @('-c', 'import tomlkit')
  & $python.Command @dependencyProbe 2>$null
  if ($LASTEXITCODE -ne 0) {
    throw 'tomlkit is missing. Rerun with -Apply -InstallDependencies.'
  }
  $helperArgs = @($python.Prefix) + @(
    (Join-Path $PSScriptRoot 'configure.py'), '--model', $Model,
    '--effort', $Effort, '--windows-sandbox', $WindowsSandbox
  )
  if ($CodexHome) { $helperArgs += @('--codex-home', $CodexHome) }
  if ($Output) { $helperArgs += @('--output', $Output) }
  if ($Apply) { $helperArgs += '--apply' }
  if ($SkipCliValidation) { $helperArgs += '--skip-cli-validation' }
  if ($PreferMxc) { $helperArgs += '--prefer-mxc' }
  if ($OverwriteAgents) { $helperArgs += '--overwrite-agents' }
  if ($Restore) { $helperArgs += @('--restore', $Restore) }
  if ($ForceRestore) { $helperArgs += '--force-restore' }
  if ($EnableCompletion -and -not $ProfileFile) {
    $ProfileFile = $PROFILE.CurrentUserCurrentHost
  }
  if ($ProfileFile) { $helperArgs += @('--profile-file', $ProfileFile) }
  if ($EnableCompletion) {
    $helperArgs += @('--enable-completion', '--powershell',
      (Join-Path $PSHOME $(if ($IsWindows) { 'pwsh.exe' } else { 'pwsh' })))
  }
  $cli = Find-CodexCommand
  if ($cli) { $helperArgs += @('--codex', $cli) }
  Invoke-CheckedCommand $python.Command $helperArgs
} catch {
  Write-Error -Message $_.Exception.Message -ErrorAction Continue
  exit 1
}
