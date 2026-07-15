# 24/7 supervisor for the paper trading bot (Windows / PowerShell).
# - Auto-restarts the bot if it crashes (after a short backoff).
# - Does NOT restart on breaker halt (exit code 42) or clean stop (exit 0).
# - Watchdog: kills the bot if its heartbeat file (logs/heartbeat.txt, written
#   once per loop pass) goes stale, forcing a restart instead of a silent
#   multi-day freeze (alpaca-py's HTTP client has no request timeout, so a
#   stalled network read can hang the process forever without crashing it).
# Run from the project folder:
#     powershell -ExecutionPolicy Bypass -File .\run_forever.ps1
Set-Location -Path $PSScriptRoot
if (-not (Test-Path "logs")) { New-Item -ItemType Directory -Path "logs" | Out-Null }

$HeartbeatFile = "logs\heartbeat.txt"
$HeartbeatMaxAgeSec = 900  # normal cadence is ~60-70s; generous margin above worst-case scan time

while ($true) {
    "[start $(Get-Date -Format o)]" | Out-File -Append -Encoding utf8 logs\bot.out
    Remove-Item -Path $HeartbeatFile -ErrorAction SilentlyContinue

    $proc = Start-Process -FilePath ".\.venv\Scripts\python.exe" -ArgumentList "-m", "bot.main" `
        -RedirectStandardOutput "logs\bot.out" -RedirectStandardError "logs\bot.err" `
        -NoNewWindow -PassThru

    while (-not $proc.HasExited) {
        Start-Sleep -Seconds 60
        if (Test-Path $HeartbeatFile) {
            $age = (Get-Date) - (Get-Item $HeartbeatFile).LastWriteTime
            if ($age.TotalSeconds -gt $HeartbeatMaxAgeSec) {
                "[watchdog] Heartbeat stale ($([int]$age.TotalSeconds)s > ${HeartbeatMaxAgeSec}s); killing hung bot (pid $($proc.Id))." | Out-File -Append -Encoding utf8 logs\bot.out
                Stop-Process -Id $proc.Id -Force -ErrorAction SilentlyContinue
                break
            }
        }
    }

    $proc.WaitForExit()
    $code = $proc.ExitCode
    "[exit code=$code $(Get-Date -Format o)]" | Out-File -Append -Encoding utf8 logs\bot.out

    if ($code -eq 42) {
        "[HALT] Drawdown circuit breaker tripped. NOT restarting. Review, then relaunch." | Out-File -Append -Encoding utf8 logs\bot.out
        break
    }
    if ($code -eq 0) {
        "[STOP] Clean exit (e.g. Ctrl-C). NOT restarting." | Out-File -Append -Encoding utf8 logs\bot.out
        break
    }
    "[restart] Unexpected exit ($code); restarting in 10s..." | Out-File -Append -Encoding utf8 logs\bot.out
    Start-Sleep -Seconds 10
}
