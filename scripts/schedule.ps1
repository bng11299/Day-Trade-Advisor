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
$Python      = (Get-Command python).Source
$ScreenerLog = "$BotRoot\scripts\screener.log"
$BacktestLog = "$BotRoot\scripts\daily_backtest.log"

$ApiKey    = $env:ALPACA_API_KEY
$SecretKey = $env:ALPACA_SECRET_KEY

if (-not $ApiKey)    { $ApiKey    = Read-Host "Enter ALPACA_API_KEY" }
if (-not $SecretKey) { $SecretKey = Read-Host "Enter ALPACA_SECRET_KEY" }

function Register-BotTask($TaskName, $ScriptPath, $LogPath, $TriggerTime, $Description, $TimeoutMin) {
    $Command  = '$env:ALPACA_API_KEY = ''' + $ApiKey + '''; $env:ALPACA_SECRET_KEY = ''' + $SecretKey + '''; & ''' + $Python + ''' ''' + $ScriptPath + ''' >> ''' + $LogPath + ''' 2>&1'
    $Action   = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NonInteractive -ExecutionPolicy Bypass -Command `"$Command`""
    $Trigger  = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At $TriggerTime
    $Settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes $TimeoutMin) -MultipleInstances IgnoreNew -StartWhenAvailable

    $Existing = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($Existing) {
        Write-Host "Task '$TaskName' already exists - replacing."
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
    }

    Register-ScheduledTask -TaskName $TaskName -Action $Action -Trigger $Trigger -Settings $Settings -RunLevel Limited -Description $Description | Out-Null
    Write-Host "Registered: $TaskName  (fires at $TriggerTime weekdays)"
}

Register-BotTask "DayTradeBot-Screener" "$BotRoot\scripts\screener.py" $ScreenerLog "9:15PM" "Screens SP500 for high-ATR/volume names. Writes watchlist.json before market open." 10
Register-BotTask "DayTradeBot-DailyBacktest" "$BotRoot\scripts\daily_backtest.py" $BacktestLog "9:25PM" "Live shadow runner: logs strategy signals during market hours, compares to actual fills at close." 420

Write-Host ""
Write-Host "Both tasks registered. Daily schedule (Singapore Time, SGT = UTC+8):"
Write-Host "  9:15pm SGT - Screener writes top-15 symbols to watchlist.json  (= 9:15am ET)"
Write-Host "  9:25pm SGT - Shadow runner starts watching those symbols        (= 9:25am ET)"
Write-Host "  4:00am SGT - Shadow runner compares signals to actual fills and exits (next morning)"
Write-Host ""
Write-Host "Useful commands:"
Write-Host "  Start-ScheduledTask -TaskName 'DayTradeBot-Screener'"
Write-Host "  Start-ScheduledTask -TaskName 'DayTradeBot-DailyBacktest'"
Write-Host "  Get-Content '$ScreenerLog' -Tail 30"
Write-Host "  Get-Content '$BacktestLog' -Tail 50 -Wait"
Write-Host ""
Write-Host "To remove tasks:"
Write-Host "  Unregister-ScheduledTask -TaskName 'DayTradeBot-Screener'      -Confirm:`$false"
Write-Host "  Unregister-ScheduledTask -TaskName 'DayTradeBot-DailyBacktest' -Confirm:`$false"
