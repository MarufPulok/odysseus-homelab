#!/usr/bin/env bash
# Toggle Ollama's Vulkan backend on an AMD iGPU (tested on Vega 8).
#   sudo bash setup/ollama-vulkan.sh on    # install ollama-vulkan, enable iGPU
#   sudo bash setup/ollama-vulkan.sh off   # back to CPU-only
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }

DROPIN=/etc/systemd/system/ollama.service.d/vulkan.conf
case "${1:-}" in
  on)
    pacman -S --needed --noconfirm ollama-vulkan
    cat > "$DROPIN" <<'EOF'
[Service]
Environment="OLLAMA_IGPU_ENABLE=1"
Environment="OLLAMA_VULKAN=1"
EOF
    ;;
  off)
    rm -f "$DROPIN"
    pacman -Q ollama-vulkan &>/dev/null && pacman -R --noconfirm ollama-vulkan
    ;;
  *) echo "usage: sudo bash $0 on|off"; exit 1 ;;
esac

# Both modes: 8k default context. Ollama otherwise picks 4k without a big GPU and
# silently truncates longer Odysseus prompts (tool schemas + email/doc text).
cat > /etc/systemd/system/ollama.service.d/context.conf <<'EOF'
[Service]
Environment="OLLAMA_CONTEXT_LENGTH=8192"
EOF

systemctl daemon-reload
systemctl restart ollama
sleep 3
journalctl -u ollama -n 40 --no-pager | grep -E 'inference compute' || true
systemctl is-active ollama
