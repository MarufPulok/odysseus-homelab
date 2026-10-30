#!/usr/bin/env bash
# One-time (and whenever the Notion login expires): open a dedicated Chrome profile and log in to Notion as yourself.
# The automations reuse this profile headless. Remote debugging listens on 127.0.0.1 only.
set -euo pipefail
profile="$HOME/.config/notion-bot-chrome"
mkdir -p "$profile"
pkill -f -- "--user-data-dir=$profile" 2>/dev/null || true
exec google-chrome-stable --user-data-dir="$profile" --remote-debugging-port=9333 --remote-debugging-address=127.0.0.1 \
  --no-first-run --no-default-browser-check "https://app.notion.com/"
