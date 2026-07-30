# schedule.ps1 - registers two Task Scheduler jobs:
#   1. DayTradeBot-Screener      - 9:15pm SGT weekdays (= 9:15am ET): screens SP500, writes watchlist.json
#   2. DayTradeBot-DailyBacktest - 9:25pm SGT weekdays (= 9:25am ET): shadow runner (reads watchlist.json)
#
# Times are in Singapore Time (SGT = UTC+8). US markets open at 9:30pm SGT, close at 4:00am SGT.
# If you move to a different timezone, adjust trigger times accordingly:
#   ET (UTC-4 EDT):  9:15am / 9:25am
#   SGT (UTC+8):     9:15pm / 9:25pm
#   GMT (UTC+0):     1:15pm / 1:25pm
#
# Run once:
#     powershell -ExecutionPolicy Bypass -File "C:\Users\Browndan\Documents\DayTradeBot\scripts\schedule.ps1"
#
# To remove tasks:
#     Unregister-ScheduledTask -TaskName "DayTradeBot-Screener"      -Confirm:$false
#     Unregister-ScheduledTask -TaskName "DayTradeBot-DailyBacktest" -Confirm:$false

$BotRoot     = "C:\Users\Browndan\Documents\DayTradeBot"
$Python      = "C:\Users\Browndan\AppData\Local\Programs\Python\Python313\python.exe"
$LogDir = "$BotRoot\scripts\logs"   # both scripts self-log here, one file per day

$ApiKey    = $env:ALPACA_API_KEY
$SecretKey = $env:ALPACA_SECRET_KEY

if (-not $ApiKey)    { $ApiKey    = Read-Host "Enter ALPACA_API_KEY" }
if (-not $SecretKey) { $SecretKey = Read-Host "Enter ALPACA_SECRET_KEY" }

function Register-BotTask($TaskName, $ScriptPath, $LogPath, $TriggerTime, $Description, $TimeoutMin) {
    # Empty $LogPath => the script self-logs (daily_backtest.py); otherwise append stdout via >>.
    $Redirect = ''
    if ($LogPath) { $Redirect = ' >> ''' + $LogPath + ''' 2>&1' }
    $Command  = '$env:ALPACA_API_KEY = ''' + $ApiKey + '''; $env:ALPACA_SECRET_KEY = ''' + $SecretKey + '''; & ''' + $Python + ''' ''' + $ScriptPath + '''' + $Redirect

    # -WorkingDirectory is required: the scripts resolve paths relative to the bot root.
    $Action   = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -ExecutionPolicy Bypass -Command `"$Command`"" -WorkingDirectory $BotRoot
    $Trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $TriggerTime
    $Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes $TimeoutMin) -MultipleInstances IgnoreNew -StartWhenAvailable
    # Don't let battery state skip or kill the run (laptop may be unplugged at trigger time).
    $Settings.DisallowStartIfOnBatteries = $false
    $Settings.StopIfGoingOnBatteries     = $false

    $Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($Existing) {
        Write-Host "Task '$TaskName' already exists - replacing."
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -RunLevel Limited -Description $Description | Out-Null
    Write-Host "Registered: $TaskName  (fires at $TriggerTime weekdays)"
}

Register-BotTask "DayTradeBot-Screener" "$BotRoot\scripts\screener.py" "" "9:15PM" "Screens SP500 for high-ATR/volume names. Writes watchlist.json before market open." 10
Register-BotTask "DayTradeBot-DailyBacktest" "$BotRoot\scripts\daily_backtest.py" "" "9:25PM" "Live shadow runner: logs strategy signals during market hours, compares to actual fills at close." 600

Write-Host ""
Write-Host "Both tasks registered. Daily schedule (Singapore Time, SGT = UTC+8):"
Write-Host "  9:15pm SGT - Screener writes top-15 symbols to watchlist.json  (= 9:15am ET)"
Write-Host "  9:25pm SGT - Shadow runner starts watching those symbols        (= 9:25am ET)"
Write-Host "  4:00am SGT - Shadow runner compares signals to actual fills and exits (next morning)"
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Start-ScheduledTask -TaskName 'DayTradeBot-Screener'"
Write-Host "  Start-ScheduledTask -TaskName 'DayTradeBot-DailyBacktest'"
Write-Host "  Get-ChildItem '$LogDir\screener_*.log' | Sort LastWriteTime | Select -Last 1 | Get-Content -Tail 30"
Write-Host "  Get-ChildItem '$LogDir\daily_backtest_*.log' | Sort LastWriteTime | Select -Last 1 | Get-Content -Tail 50 -Wait"
Write-Host ""
Write-Host "To remove tasks:"
Write-Host "  Unregister-ScheduledTask -TaskName 'DayTradeBot-Screener'      -Confirm:`$false"
Write-Host "  Unregister-ScheduledTask -TaskName 'DayTradeBot-DailyBacktest' -Confirm:`$false"
