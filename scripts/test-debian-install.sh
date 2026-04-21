#!/bin/bash
# Run inside a debian:12 container to verify the Debian 12 + XFCE +
# Docker CE install path works end-to-end. Mirrors what cloud-init does.
set -e

echo "=== apt update + base packages ==="
apt-get update -qq
apt-get install -y -qq --no-install-recommends curl gnupg ca-certificates lsb-release >/dev/null

echo "=== Docker CE repo add ==="
curl -fsSL https://download.docker.com/linux/debian/gpg \
  | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
echo 'deb [arch=amd64 signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian bookworm stable' \
  > /etc/apt/sources.list.d/docker.list
apt-get update -qq 2>&1 | grep docker.com | tail -3

echo "=== Docker CE install (cli only) ==="
apt-get install -y -qq --no-install-recommends docker-ce-cli >/dev/null
docker --version

echo "=== XFCE + xrdp resolve (dry-run) ==="
count=$(apt-get install -y --simulate --no-install-recommends \
  task-xfce-desktop xrdp xorgxrdp xfce4-terminal dbus-x11 \
  policykit-1-gnome greybird-gtk-theme papirus-icon-theme 2>&1 \
  | grep -c '^Inst ')
echo "  resolves cleanly: $count packages would install"

echo "=== all checks passed ==="
