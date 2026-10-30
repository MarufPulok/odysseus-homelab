#!/usr/bin/env bash
# Root setup for an Arch/Manjaro box. Run with: sudo bash setup/setup-root.sh
# Safe to re-run: every step checks or overwrites its own config.
set -euo pipefail

[[ $EUID -eq 0 ]] || { echo "Run with sudo."; exit 1; }
TARGET_USER="${SUDO_USER:?run with sudo from your normal user}"
LOG="/home/$TARGET_USER/setup-root.log"
exec > >(tee -a "$LOG") 2>&1
step() { printf '\n=== %s ===\n' "$*"; }

# ---------------------------------------------------------------- snapshots
step "Timeshift: configure btrfs mode and take a pre-update snapshot"
ROOT_FS=$(findmnt -no FSTYPE /)
if [[ $ROOT_FS == btrfs ]]; then
  ROOT_UUID=$(findmnt -no UUID /)
  TS=/etc/timeshift/timeshift.json
  [[ -f $TS ]] && cp -n "$TS" "$TS.orig"
  sed -i \
    -e "s/\"backup_device_uuid\" : \"[^\"]*\"/\"backup_device_uuid\" : \"$ROOT_UUID\"/" \
    -e 's/"do_first_run" : "true"/"do_first_run" : "false"/' \
    -e 's/"btrfs_mode" : "false"/"btrfs_mode" : "true"/' \
    -e 's/"schedule_daily" : "false"/"schedule_daily" : "true"/' \
    -e 's/"schedule_weekly" : "false"/"schedule_weekly" : "true"/' \
    "$TS"
  if timeshift --list 2>/dev/null | grep -q "before homelab-setup"; then
    echo "Pre-setup snapshot already exists, not taking another."
  else
    timeshift --create --comments "before homelab-setup" --tags O
  fi
  # Make grub-btrfsd watch Timeshift's snapshot dir so snapshots show in the boot menu.
  mkdir -p /etc/systemd/system/grub-btrfsd.service.d
  cat > /etc/systemd/system/grub-btrfsd.service.d/override.conf <<'EOF'
[Service]
ExecStart=
ExecStart=/usr/bin/grub-btrfsd --syslog --timeshift-auto
EOF
  systemctl daemon-reload
  systemctl enable cronie
else
  echo "Root is $ROOT_FS, not btrfs: skipping snapshots."
fi

# ---------------------------------------------------------------- update
step "Fastest mirrors + full system update"
KERNEL_BEFORE=$(pacman -Q | awk '/^linux[0-9]+ /{print $1" "$2}')
pacman-mirrors --fasttrack 5
pacman -Syyu --noconfirm
KERNEL_AFTER=$(pacman -Q | awk '/^linux[0-9]+ /{print $1" "$2}')

# ---------------------------------------------------------------- packages
step "Install ufw, Docker, Compose, Tailscale, Ollama (CPU build)"
pacman -S --needed --noconfirm ufw docker docker-compose docker-buildx tailscale ollama

# ---------------------------------------------------------------- hostname
if [[ -n ${NEW_HOSTNAME:-} ]]; then  # optional: sudo NEW_HOSTNAME=homelab bash setup/setup-root.sh
  step "Hostname: $NEW_HOSTNAME"
  hostnamectl set-hostname "$NEW_HOSTNAME"
  grep -qE "^127\.0\.1\.1[[:space:]]+$NEW_HOSTNAME" /etc/hosts || echo "127.0.1.1 $NEW_HOSTNAME" >> /etc/hosts
fi

# ---------------------------------------------------------------- docker
step "Docker: loopback-only default publish address, pinned docker0, log rotation"
mkdir -p /etc/docker
[[ -f /etc/docker/daemon.json ]] && cp -n /etc/docker/daemon.json /etc/docker/daemon.json.orig
cat > /etc/docker/daemon.json <<'EOF'
{
  "ip": "127.0.0.1",
  "bip": "172.17.0.1/16",
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
usermod -aG docker "$TARGET_USER"
systemctl enable docker.service

# ---------------------------------------------------------------- ollama
step "Ollama: listen only on the docker0 gateway, unload idle models"
mkdir -p /etc/systemd/system/ollama.service.d
cat > /etc/systemd/system/ollama.service.d/override.conf <<'EOF'
[Unit]
# docker0 (172.17.0.1) must exist before Ollama can bind to it.
After=docker.service
Wants=docker.service

[Service]
Environment="OLLAMA_HOST=172.17.0.1:11434"
Environment="OLLAMA_KEEP_ALIVE=5m"
Environment="OLLAMA_MAX_LOADED_MODELS=1"
Environment="OLLAMA_NUM_PARALLEL=1"
ExecStartPre=/bin/sh -c 'for i in $(seq 30); do ip -4 addr show docker0 2>/dev/null | grep -q "inet 172.17.0.1/" && exit 0; sleep 1; done; echo "docker0 not up"; exit 1'
Restart=on-failure
RestartSec=5
EOF
systemctl daemon-reload
systemctl enable ollama.service

# ---------------------------------------------------------------- tailscale
step "Tailscale: enable tailscaled"
systemctl enable tailscaled.service

# ---------------------------------------------------------------- ssh
step "SSH server"
cat > /etc/ssh/sshd_config.d/50-dell.conf <<'EOF'
PermitRootLogin no
EOF
systemctl enable sshd.service

# ---------------------------------------------------------------- firewall
step "ufw: deny incoming; SSH/HTTPS only via Tailscale; Ollama only from the Odysseus bridge"
ufw --force reset >/dev/null
ufw default deny incoming
ufw default allow outgoing
ufw allow in on tailscale0 to any port 22 proto tcp comment 'ssh via tailscale'
ufw allow in on tailscale0 to any port 443 proto tcp comment 'tailscale serve (odysseus)'
ufw allow in on br-odysseus to 172.17.0.1 port 11434 proto tcp comment 'ollama from odysseus containers'
ufw --force enable
systemctl enable ufw.service
ufw status verbose

# ---------------------------------------------------------------- start / reboot check
step "Start services (if the running kernel allows it)"
if [[ ! -d /usr/lib/modules/$(uname -r) || "$KERNEL_BEFORE" != "$KERNEL_AFTER" ]]; then
  echo "REBOOT REQUIRED: running kernel $(uname -r), installed: $KERNEL_AFTER."
  echo "Services are enabled and will start on boot. Reboot before testing Docker."
else
  systemctl start sshd docker tailscaled ollama
  docker compose version
  echo "No reboot required (kernel unchanged)."
fi

step "Done"
echo "Installed: $(pacman -Q docker docker-compose tailscale ollama ufw | tr '\n' ' ')"
echo "Log saved to $LOG"
