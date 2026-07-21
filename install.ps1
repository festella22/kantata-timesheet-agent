# install.ps1 - deploy the weekly Kantata timesheet task onto this machine.
# NOTE: keep this file pure ASCII - PowerShell 5.1 reads BOM-less files as ANSI
# and non-ASCII characters can corrupt the parse.
# Run from the repo root:  powershell -ExecutionPolicy Bypass -File .\install.ps1
# Safe to re-run: updates the skill, never overwrites config you already filled in.

$claudeDir = Join-Path $env:USERPROFILE ".claude"
$taskDir   = Join-Path $claudeDir "scheduled-tasks\weekly-kantata-timesheet"
$cfgDir    = Join-Path $claudeDir "kantata-timesheet"

New-Item -ItemType Directory -Force $taskDir | Out-Null
New-Item -ItemType Directory -Force $cfgDir  | Out-Null

Copy-Item "$PSScriptRoot\.claude\scheduled-tasks\weekly-kantata-timesheet\SKILL.md" $taskDir -Force

if (-not (Test-Path "$cfgDir\project_mapping.yaml")) {
    Copy-Item "$PSScriptRoot\config\project_mapping.yaml" "$cfgDir\project_mapping.yaml"
}
if (-not (Test-Path "$cfgDir\kantata.env")) {
    Copy-Item "$PSScriptRoot\config\kantata.env.example" "$cfgDir\kantata.env"
}

Write-Host ""
Write-Host "Installed. Two files to fill in before the first run:"
Write-Host "  1. $cfgDir\kantata.env            <- your Kantata API token"
Write-Host "  2. $cfgDir\project_mapping.yaml   <- your project/task IDs"
Write-Host ""
Write-Host "Then open Claude, make sure the Microsoft 365 connector is authorized,"
Write-Host "and check Scheduled Tasks: 'weekly-kantata-timesheet' runs Mon & Tue 8 AM."
Write-Host "(Tip: run it once manually - with placeholder config it emails you a"
Write-Host "setup checklist including your Kantata project IDs.)"
