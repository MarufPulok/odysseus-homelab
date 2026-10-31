#!/usr/bin/env bash
# Install/refresh the systemd user timers for ~/automations. Safe to re-run.
# Usage: install-timers.sh [job ...]   (no args = all jobs)
set -euo pipefail
dir="$HOME/automations"
units="$HOME/.config/systemd/user"
mkdir -p "$units"

# name | OnCalendar | command args | Persistent (catch up after the Dell was off)
jobs=(
  "auto-watchdog|*:0/5|watchdog.py|false"
  "auto-report|*-*-* 00:55|watchdog.py report|false"
  "auto-notion|*-*-* 11,14,17,20,23:40|notion_sync.py|true|venv"
  "auto-brief|*-*-* 12:25|brief.py|true"
  "auto-prep|*:0/10|prep.py|false"
  "auto-meetnotes|*:0/5|meeting_notes.py|false"
  "auto-weekly|Fri *-*-* 22:40|weekly.py|true"
  "auto-releases|Mon *-*-* 10:00|releases.py|true"
  "auto-vulns|*-*-* 0/2:10|vulns.py|true"
  "auto-backup|*-*-* 03:30|backup.py|true"
  "auto-guard|*:0/5|backup.py guard|false"
  "auto-slacktodos|*:0/15|slack_todos.py|false"
  "auto-jobs|*-*-* 10,14,18,22:30|jobs.py|true"
  "auto-jobdigest|*-*-* 20:00|jobs.py digest|true"
)

want=("$@")
for j in "${jobs[@]}"; do
  IFS='|' read -r name cal cmd persist py <<<"$j"
  python=/usr/bin/python3; [[ ${py:-} == venv ]] && python="$dir/.venv/bin/python"  # needs websockets: python3 -m venv .venv && .venv/bin/pip install websockets
  if (( ${#want[@]} )) && [[ ! " ${want[*]} " == *" $name "* ]]; then continue; fi
  cat >"$units/$name.service" <<EOF
[Unit]
Description=$name ($cmd)
After=network-online.target

[Service]
Type=oneshot
WorkingDirectory=$dir
ExecStart=$python $dir/$cmd
EOF
  cat >"$units/$name.timer" <<EOF
[Unit]
Description=$name timer

[Timer]
OnCalendar=$cal
Persistent=$persist
RandomizedDelaySec=20

[Install]
WantedBy=timers.target
EOF
  systemctl --user daemon-reload
  systemctl --user enable --now "$name.timer" >/dev/null
  echo "enabled $name  ($cal)"
done

# Long-running services (restart on failure): name | command
services=(
  "auto-capture|capture.py"
)
for s in "${services[@]}"; do
  IFS="|" read -r name cmd <<<"$s"
  if (( ${#want[@]} )) && [[ ! " ${want[*]} " == *" $name "* ]]; then continue; fi
  cat >"$units/$name.service" <<UNIT
[Unit]
Description=$name ($cmd)
After=network-online.target

[Service]
WorkingDirectory=$dir
ExecStart=/usr/bin/python3 $dir/$cmd
Restart=always
RestartSec=10

[Install]
WantedBy=default.target
UNIT
  systemctl --user daemon-reload
  systemctl --user enable --now "$name.service" >/dev/null
  systemctl --user restart "$name.service"
  echo "enabled $name  (service)"
done
