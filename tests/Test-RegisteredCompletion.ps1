#requires -Version 7.4
<#
.SYNOPSIS
  Load a staged profile and check the generated Codex completion registration.
.EXAMPLE
  .\tests\Test-RegisteredCompletion.ps1 -Path .\temporary-profile.ps1
#>
[CmdletBinding()]
param([Parameter(Mandatory)][string]$Path)

$ErrorActionPreference = 'Stop'
. $Path
$line = 'codex --mo'
$matches = (TabExpansion2 $line $line.Length).CompletionMatches
if (@($matches | Where-Object CompletionText -EQ '--model').Count -eq 0) {
  throw 'The staged profile did not register --model completion.'
}
Write-Host 'Generated completion registered and expanded --model.'
