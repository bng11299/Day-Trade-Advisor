# schedule.ps1 — registers the daily backtest as a Windows Task Scheduler job.
#
# Run once (as administrator not required — runs under your own user account):
#     powershell -ExecutionPolicy Bypass -File "C:\Users\Browndan\Documents\DayTradeBot\scripts\schedule.ps1"
#
# To remove the task later:
#     Unregister-ScheduledTask -TaskName "DayTradeBot-DailyBacktest" -Confirm:$false

$TaskName   = "DayTradeBot-DailyBacktest"
$BotRoot    = "C:\Users\Browndan\Documents\DayTradeBot"
$ScriptPath = "$BotRoot\scripts\daily_backtest.py"
$LogPath    = "$BotRoot\scripts\daily_backtest.log"
$Python     = (Get-Command python).Source

# ── read API keys from current session or prompt ──────────────────────────────
$ApiKey    = $env:ALPACA_API_KEY
$SecretKey = $env:ALPACA_SECRET_KEY

if (-not $ApiKey) {
    $ApiKey    = Read-Host "Enter ALPACA_API_KEY"
}
if (-not $SecretKey) {
    $SecretKey = Read-Host "Enter ALPACA_SECRET_KEY"
}

# ── build the command that Task Scheduler will run ────────────────────────────
# Sets env vars inline so the task doesn't depend on user session variables.
$Command = @"
`$env:ALPACA_API_KEY = '$ApiKey'; `$env:ALPACA_SECRET_KEY = '$SecretKey'; & '$Python' '$ScriptPath' >> '$LogPath' 2>&1
"@

$Action = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -ExecutionPolicy Bypass -Command `"$Command`""

# ── trigger: weekdays at 5:00pm (after market close at 4pm ET) ───────────────
$Trigger = New-ScheduledTaskTrigger `
    -Weekly `
    -DaysOfWeek Monday, Tuesday, Wednesday, Thursday, Friday `
    -At "5:00PM"

# ── settings: run even if on battery, skip if already running ────────────────
$Settings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew `
    -StartWhenAvailable   # catches up if machine was off at trigger time

# ── register ──────────────────────────────────────────────────────────────────
$Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
if ($Existing) {
    Write-Host "Task '$TaskName' already exists — updating it."
    Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
}

Register-ScheduledTask `
    -TaskName $TaskName `
    -Action   $Action `
    -Trigger  $Trigger `
    -Settings $Settings `
    -RunLevel Limited `
    -Description "Runs the DayTradeBot daily backtest each weekday at 5pm. 30-day paper trading evaluation period." | Out-Null

Write-Host ""
Write-Host "Task '$TaskName' registered successfully."
Write-Host "  Runs:    Weekdays at 5:00 PM"
Write-Host "  Script:  $ScriptPath"
Write-Host "  Log:     $LogPath"
Write-Host "  Catches missed days when machine comes back on."
Write-Host ""
Write-Host "To run immediately (test):"
Write-Host "  Start-ScheduledTask -TaskName '$TaskName'"
Write-Host ""
Write-Host "To view the log:"
Write-Host "  Get-Content '$LogPath' -Tail 50"
Write-Host ""
Write-Host "To remove the task:"
Write-Host "  Unregister-ScheduledTask -TaskName '$TaskName' -Confirm:`$false"
