#requires -Version 7.4
<#
.SYNOPSIS
  Parse a generated completion file without executing its content.
.EXAMPLE
  .\scripts\Test-Completion.ps1 -Path .\preview\completion.powershell.ps1
#>
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Path)

$tokens = $null
$parseErrors = $null
$null = [System.Management.Automation.Language.Parser]::ParseFile(
  $Path, [ref]$tokens, [ref]$parseErrors
)
if ($parseErrors.Count -gt 0) {
  $parseErrors | ForEach-Object { Write-Error $_.Message }
  exit 1
}
exit 0
