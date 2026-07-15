#!/usr/bin/env bash
# 24/7 supervisor for the paper trading bot.
# - Auto-restarts the bot if it crashes (after a short backoff).
# - Does NOT restart if the 10% drawdown circuit breaker tripped (exit code 42),
#   so a halt stays halted until you manually review and relaunch.
# - Watchdog: kills the bot if its heartbeat file (logs/heartbeat.txt, written
#   once per loop pass) goes stale, which forces a restart instead of a silent
#   multi-day freeze. This is what happened on 2026-07-03: a blocking network
#   call with no timeout hung forever while the process stayed "alive", so
#   nothing (launchd included) noticed for days.
# - Runs the bot under `caffeinate` so this Mac won't idle/system-sleep while it
#   trades (repeated overnight restarts on 2026-07-06/07 were caused by the
#   machine sleeping, not a code bug — every process, including this script,
#   just froze until it woke up). NOTE: caffeinate CANNOT override lid-close
#   sleep — closing the lid still sleeps the Mac regardless. Keep the lid open
#   (or use clamshell mode with an external display) for true 24/7 uptime.
# Logs go to logs/bot.out. Start detached with:
#     nohup ./run_forever.sh >/dev/null 2>&1 &
set -u
cd "$(dirname "$0")"
mkdir -p logs

HEARTBEAT_FILE="logs/heartbeat.txt"
# Normal loop cadence is ~60-70s. This is set well above the worst-case scan
# time (all instruments timing out at once with the 5s/15s connect/read caps)
# so it only fires on a genuine hang, not a slow-but-alive network.
HEARTBEAT_MAX_AGE=900

_mtime() {
  stat -f %m "$1" 2>/dev/null || stat -c %Y "$1" 2>/dev/null
}

watchdog() {
  local bot_pid="$1"
  while kill -0 "$bot_pid" 2>/dev/null; do
    sleep 60
    if [ -f "$HEARTBEAT_FILE" ]; then
      now=$(date +%s)
      mtime=$(_mtime "$HEARTBEAT_FILE")
      if [ -n "${mtime:-}" ] && [ $((now - mtime)) -gt "$HEARTBEAT_MAX_AGE" ]; then
        echo "[watchdog] Heartbeat stale ($((now - mtime))s > ${HEARTBEAT_MAX_AGE}s); killing hung bot (pid $bot_pid)." >> logs/bot.out
        # Belt-and-suspenders kill: in a non-interactive script (no `set -m`),
        # background jobs do NOT get their own process group -- they inherit
        # the script's pgid. So "kill -- -$bot_pid" (process-group kill)
        # silently no-ops because no group with that pgid exists, and the
        # "hung" process just keeps running. Confirmed via `ps -o pgid` on
        # 2026-07-08: bash/python/caffeinate all shared the script's own pgid.
        # Cover every case: kill any real process group (if one exists),
        # kill direct children by pid (e.g. caffeinate's monitor child), and
        # kill the pid itself directly.
        kill -9 -- -"$bot_pid" 2>/dev/null
        pkill -9 -P "$bot_pid" 2>/dev/null
        kill -9 "$bot_pid" 2>/dev/null
        return
      fi
    fi
  done
}

while true; do
  echo "[start $(date -u +%FT%TZ)]" >> logs/bot.out
  rm -f "$HEARTBEAT_FILE"
  # -i: no idle sleep, -m: no disk sleep, -s: no system sleep (AC power only).
  # caffeinate forwards python's real exit code, so the branching below is
  # unaffected by wrapping it.
  MPLCONFIGDIR=/tmp/mpl caffeinate -ims ./.venv/bin/python -m bot.main >> logs/bot.out 2>&1 &
  bot_pid=$!
  watchdog "$bot_pid" &
  watchdog_pid=$!

  wait "$bot_pid"
  code=$?
  kill "$watchdog_pid" 2>/dev/null || true

  echo "[exit code=$code $(date -u +%FT%TZ)]" >> logs/bot.out

  if [ "$code" -eq 42 ]; then
    echo "[HALT] Drawdown circuit breaker tripped. NOT restarting. Review, then relaunch manually." >> logs/bot.out
    break
  fi
  if [ "$code" -eq 0 ]; then
    echo "[STOP] Clean exit (e.g. Ctrl-C). NOT restarting." >> logs/bot.out
    break
  fi
  echo "[restart] Unexpected exit ($code); restarting in 10s..." >> logs/bot.out
  sleep 10
done
