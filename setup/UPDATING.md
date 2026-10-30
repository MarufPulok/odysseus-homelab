UPDATE ROUTINE - dell (Manjaro stable, btrfs + Timeshift)
==========================================================

1. Snapshot first (the pacman hook also takes one automatically):
     sudo timeshift --create --comments "before update" --tags O

2. Update the system:
     sudo pacman-mirrors --fasttrack 5      # optional, if downloads are slow
     sudo pacman -Syu

3. Reboot if the kernel changed. Check:
     ls /usr/lib/modules/ | grep -qx "$(uname -r)" && echo "no reboot needed" || echo "REBOOT NOW"
   Docker networking, ufw (nftables) and Tailscale break until you reboot
   after a kernel update.

4. After the update / reboot, check everything is up:
     cd ~/odysseus && docker compose ps            # 4 containers "Up"
     systemctl is-active docker ollama tailscaled ufw sshd
     tailscale serve status                        # https://dell.<your-tailnet>.ts.net -> 127.0.0.1:7011
     sudo ufw status

5. Update Odysseus (occasionally, not on every system update):
     cd ~/odysseus && git pull && docker compose pull && docker compose up -d

6. If something broke: reboot and choose a Timeshift snapshot from the GRUB
   menu ("Manjaro snapshots"), or run: sudo timeshift --restore

Notes
- Ollama listens only on 172.17.0.1:11434 (docker0). For the CLI:
    export OLLAMA_HOST=172.17.0.1:11434   (already in ~/.zshrc)
- Local models: qwen3:4b-instruct-2507-q4_K_M (in use), qwen3.5:4b (unused).
- Vulkan on/off: sudo bash setup/ollama-vulkan.sh on|off
- Root setup scripts: setup/setup-root.sh, setup/ollama-vulkan.sh,
  setup/tailscale-serve.sh (undo with: sudo tailscale serve reset)
