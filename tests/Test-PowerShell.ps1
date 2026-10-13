#requires -Version 7.4
<#
.SYNOPSIS
  Check PowerShell syntax and installer behavior in temporary directories.
.DESCRIPTION
  No package installation, login or real-home mutation occurs. Python/tomlkit
  must be available, using the same detection as the wrapper. Runs on Linux and
  Windows; the junction check additionally runs on native Windows.
.EXAMPLE
  pwsh -NoProfile -File .\tests\Test-PowerShell.ps1
#>
[CmdletBinding()]
param()

Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$launcher = Join-Path $root 'setup-codex-windows.ps1'
$pwsh = Join-Path $PSHOME $(if ($IsWindows) { 'pwsh.exe' } else { 'pwsh' })
$temporary = Join-Path ([IO.Path]::GetTempPath()) (
  "kit O'Brien ü [tests]-" + [guid]::NewGuid().ToString('N')
)
$null = New-Item -ItemType Directory -Path $temporary
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
  $files = Get-ChildItem -LiteralPath $root -Recurse -Filter '*.ps1' -File |
    Where-Object { $_.FullName -notmatch '[\\/]\.venv[\\/]' }
  foreach ($file in $files) {
    $tokens = $null
    $parseErrors = $null
    $null = [System.Management.Automation.Language.Parser]::ParseFile(
      $file.FullName, [ref]$tokens, [ref]$parseErrors
    )
    Assert-Condition ($parseErrors.Count -eq 0) "Syntax: $($file.Name)"
  }
  # Exercise discovery alone, without running setup or installing anything.
  $launcherAst = [System.Management.Automation.Language.Parser]::ParseFile(
    $launcher, [ref]$null, [ref]$null
  )
  $pythonFunction = $launcherAst.Find({
    param($node)
    $node -is [System.Management.Automation.Language.FunctionDefinitionAst] `
      -and $node.Name -eq 'Find-PythonCommand'
  }, $true)
  & {
    . ([scriptblock]::Create($pythonFunction.Extent.Text))
    $oldPython = Join-Path $temporary 'old-python.ps1'
    $workingPython = Join-Path $temporary 'working-python.ps1'
    Set-Content -LiteralPath $oldPython -Value '$global:LASTEXITCODE = 1'
    Set-Content -LiteralPath $workingPython -Value '$global:LASTEXITCODE = 0'
    $pythonName = 'python'
    $pythonResults = @(
      [pscustomobject]@{ Source = 'C:/WindowsApps/python.exe' },
      [pscustomobject]@{ Source = $oldPython },
      [pscustomobject]@{ Source = $workingPython }
    )
    function Get-Command {
      [CmdletBinding()]
      param([string]$Name, [object]$CommandType, [switch]$All)
      if ($Name -eq $pythonName) { return $pythonResults }
    }
    $selected = Find-PythonCommand -IgnoreVenv
    Assert-Condition ($selected.Command -eq $workingPython) `
      'Multiple Python paths are probed separately; Store shortcut is skipped'
    $pythonResults = @(
      [pscustomobject]@{ Source = $workingPython },
      [pscustomobject]@{ Source = $oldPython }
    )
    $selected = Find-PythonCommand -IgnoreVenv
    Assert-Condition ($selected.Command -eq $workingPython `
      -and -not $selected.Prefix) `
      'First usable PATH Python wins without a pinned version'
    $pythonName = 'py'
    $selected = Find-PythonCommand -IgnoreVenv
    Assert-Condition ($selected.Prefix -eq '-3') `
      'Windows launcher remains a fallback'
    $pythonResults = @()
    $rejected = $false
    try { $null = Find-PythonCommand -IgnoreVenv } catch {
      $rejected = $_.Exception.Message -match 'Python 3.11\+ was not found'
    }
    Assert-Condition $rejected 'Missing usable Python reports a clear error'
  }
  $result = Invoke-Launcher @('-Help')
  Assert-Condition ($result.Code -eq 0 -and $result.Text -match 'Usage:') 'Help'
  $result = Invoke-Launcher @('-Bootstrap')
  $rejectedInstall = $result.Code -ne 0 -and $result.Text -match 'require -Apply'
  Assert-Condition $rejectedInstall `
    'Bootstrap cannot install during preview'
  $result = Invoke-Launcher @('-Apply', '-SkipCliValidation')
  Assert-Condition ($result.Code -ne 0 -and $result.Text -match 'requires CLI') `
    'Offline apply rejected'
  $result = Invoke-Launcher @('-Effort', 'made-up')
  Assert-Condition ($result.Code -ne 0) 'Invalid effort rejected'
  $homePath = Join-Path $temporary 'home'
  $previewPath = Join-Path $temporary 'preview'
  $result = Invoke-Launcher @(
    '-SkipCliValidation', '-CodexHome', $homePath, '-Output', $previewPath,
    '-Effort', 'max'
  )
  Assert-Condition ($result.Code -eq 0) "Preview accepts path characters"
  Assert-Condition (-not (Test-Path -LiteralPath $homePath)) `
    'Preview leaves home absent'
  $config = Get-Content -LiteralPath (Join-Path $previewPath 'config.toml') -Raw
  Assert-Condition ($config -match 'model_reasoning_effort = "max"') `
    'Effort forwarded correctly'
  $result = Invoke-Launcher @(
    '-SkipCliValidation', '-CodexHome', $homePath, '-Output', $previewPath
  )
  Assert-Condition ($result.Code -ne 0) 'Existing preview is not overwritten'
  if ($IsWindows) {
    $target = Join-Path $temporary 'junction-target'
    $junction = Join-Path $temporary 'junction'
    $null = New-Item -ItemType Directory -Path $target
    $null = New-Item -ItemType Junction -Path $junction -Target $target
    $result = Invoke-Launcher @(
      '-SkipCliValidation', '-CodexHome', $junction,
      '-Output', (Join-Path $temporary 'junction-preview')
    )
    $rejectedLink = $result.Code -ne 0 -and $result.Text -match 'reparse point'
    Assert-Condition $rejectedLink `
      'Windows junction rejected'
  }
  Write-Host "PowerShell checks passed: $checks"
} finally {
  Remove-Item -LiteralPath $temporary -Recurse -Force
}
