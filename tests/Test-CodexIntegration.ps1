#requires -Version 7.4
<#
.SYNOPSIS
  Test the real wrapper/CLI apply, completion, repeat-apply and restore paths.
.DESCRIPTION
  Requires an installed Codex CLI and Python/tomlkit. All writes go into a
  temporary home/profile; no login, package installs or model inference occurs.
  The Windows sandbox is configured but is not exercised by these checks.
.PARAMETER Codex
  Codex executable; use an absolute path when it is not on PATH.
.EXAMPLE
  pwsh -NoProfile -File .\tests\Test-CodexIntegration.ps1 -Codex codex.exe
#>
[CmdletBinding()]
param([string]$Codex = 'codex')

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$launcher = Join-Path $root 'setup-codex-windows.ps1'
$pwsh = Join-Path $PSHOME $(if ($IsWindows) { 'pwsh.exe' } else { 'pwsh' })
$temporary = Join-Path ([IO.Path]::GetTempPath()) (
  "kit O'Brien ü [integration]-" + [guid]::NewGuid().ToString('N')
)
$homePath = Join-Path $temporary 'home'
$profilePath = Join-Path $temporary 'profile.ps1'
$null = New-Item -ItemType Directory -Path $homePath
$originalConfig = "# My setting`r`nmodel = `"before`"`r`n"
$originalProfile = "# Existing profile`r`n`$kept = 'æøå'`r`n"
[IO.File]::WriteAllText((Join-Path $homePath 'config.toml'), $originalConfig)
[IO.File]::WriteAllText($profilePath, $originalProfile)
$checks = 0

function Assert-Condition {
  param([bool]$Condition, [string]$Message)
  if (-not $Condition) { throw $Message }
  $script:checks += 1
  Write-Host "PASS: $Message"
}

function Invoke-Launcher {
  param([string[]]$ArgumentList)
  $text = & $pwsh -NoProfile -File $launcher @ArgumentList 2>&1 | Out-String
  return [pscustomobject]@{ Code = $LASTEXITCODE; Text = $text }
}

try {
  $common = @('-Codex', $Codex, '-CodexHome', $homePath,
    '-EnableCompletion', '-ProfileFile', $profilePath)
  $result = Invoke-Launcher ($common + @(
    '-Output', (Join-Path $temporary 'preview')
  ))
  Assert-Condition ($result.Code -eq 0) 'Real CLI validates preview'
  $current = [IO.File]::ReadAllText((Join-Path $homePath 'config.toml'))
  Assert-Condition ($current -ceq $originalConfig) 'Preview preserves original'
  $result = Invoke-Launcher ($common + @(
    '-Apply', '-Output', (Join-Path $temporary 'apply')
  ))
  Assert-Condition ($result.Code -eq 0) 'Real wrapper applies validated config'
  $current = Get-Content -LiteralPath (Join-Path $homePath 'config.toml') -Raw
  Assert-Condition ($current -match 'model = "gpt-6-astra"') 'Astra installed'
  Assert-Condition ($current -match 'model_reasoning_effort = "ultra"') `
    'Bundled Astra catalogue selects Ultra'
  Assert-Condition ($current -match '# My setting') 'Comment survives merge'
  $agents = @(Get-ChildItem -LiteralPath (Join-Path $homePath 'agents') -File)
  Assert-Condition ($agents.Count -eq 4) 'Four standalone agents installed'
  $completionCheck = Join-Path $PSScriptRoot 'Test-RegisteredCompletion.ps1'
  & $pwsh -NoProfile -File $completionCheck -Path $profilePath
  Assert-Condition ($LASTEXITCODE -eq 0) 'Completion loads and expands --model'
  $result = Invoke-Launcher ($common + @(
    '-Apply', '-Output', (Join-Path $temporary 'repeat')
  ))
  Assert-Condition ($result.Code -eq 0 -and
    $result.Text -match 'no writes or additional backup') `
    'Repeated apply is idle'
  $backupRoot = Join-Path $homePath 'windows-kit-backups'
  $backups = @(Get-ChildItem -LiteralPath $backupRoot -Directory)
  Assert-Condition ($backups.Count -eq 1) 'Exactly one backup created'
  $result = Invoke-Launcher @(
    '-CodexHome', $homePath, '-Restore', 'latest', '-ProfileFile', $profilePath
  )
  Assert-Condition ($result.Code -eq 0 -and $result.Text -match 'PREVIEW') `
    'Restore previews by default'
  $result = Invoke-Launcher @(
    '-CodexHome', $homePath, '-Restore', 'latest', '-ProfileFile', $profilePath,
    '-Apply'
  )
  Assert-Condition ($result.Code -eq 0) 'Restore succeeds through wrapper'
  $current = [IO.File]::ReadAllText((Join-Path $homePath 'config.toml'))
  Assert-Condition ($current -ceq $originalConfig) 'Original config restored'
  Assert-Condition ([IO.File]::ReadAllText($profilePath) -ceq $originalProfile) `
    'Original profile restored'
  $instructionsPath = Join-Path $homePath 'AGENTS.md'
  Assert-Condition (-not (Test-Path -LiteralPath $instructionsPath)) `
    'New instructions removed by restore'
  $invalidHome = Join-Path $temporary 'invalid-home'
  $null = New-Item -ItemType Directory -Path $invalidHome
  $invalidConfig = Join-Path $invalidHome 'config.toml'
  [IO.File]::WriteAllText($invalidConfig, "unrecognized_kit_test = true`n")
  $result = Invoke-Launcher @(
    '-Codex', $Codex, '-CodexHome', $invalidHome, '-Apply',
    '-Output', (Join-Path $temporary 'invalid-preview')
  )
  Assert-Condition ($result.Code -ne 0 -and
    $result.Text -match 'unknown configuration field') `
    'Strict parsing rejects typo'
  Assert-Condition (-not (Test-Path -LiteralPath (
    Join-Path $invalidHome 'windows-kit-backups'
  ))) 'Rejected config creates no transaction'
  Write-Host "Real Codex integration checks passed: $checks"
} finally {
  Remove-Item -LiteralPath $temporary -Recurse -Force
}
