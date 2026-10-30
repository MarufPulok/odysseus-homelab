#!/usr/bin/env bash
# Publish Odysseus to the tailnet only, over HTTPS.
#   sudo bash setup/tailscale-serve.sh
# Undo: sudo tailscale serve reset
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }
TARGET_USER="${SUDO_USER:?run with sudo from your normal user}"

# Let the desktop user manage `tailscale serve` without sudo from now on.
tailscale set --operator="$TARGET_USER"

# Tailnet-only HTTPS proxy -> Odysseus on loopback. `serve` (not `funnel`)
# never exposes anything to the public internet. --bg persists across reboots.
tailscale serve --bg --https=443 http://127.0.0.1:7011
tailscale serve --bg --https=8443 http://127.0.0.1:8091  # ntfy for phone notifications
tailscale serve status
