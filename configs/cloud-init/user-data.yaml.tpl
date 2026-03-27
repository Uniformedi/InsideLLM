#cloud-config
# =============================================================================
# Cloud-init: Ubuntu 24.04 provisioning for Inside LLM
# =============================================================================

hostname: ${hostname}
fqdn: ${fqdn}
manage_etc_hosts: true
timezone: America/Chicago

# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------
users:
  - default
  - name: ${ssh_admin_user}
    groups: [sudo, docker]
    shell: /bin/bash
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock_passwd: true
    ssh_authorized_keys:
      - ${ssh_public_key}

# ---------------------------------------------------------------------------
# Package Installation
# ---------------------------------------------------------------------------
package_update: true
package_upgrade: true
packages:
  - apt-transport-https
  - ca-certificates
  - curl
  - gnupg
  - lsb-release
  - ufw
  - jq
  - htop
  - net-tools
  - unzip
  - git
  - genisoimage

# ---------------------------------------------------------------------------
# Write configuration files
# ---------------------------------------------------------------------------
write_files:
  # --- Docker Compose ---
  - path: /opt/InsideLLM/docker-compose.yml
    permissions: "0640"
    owner: root:root
    content: |
      ${indent(6, docker_compose_yml)}

  # --- LiteLLM Config ---
  - path: /opt/InsideLLM/litellm-config.yaml
    permissions: "0640"
    owner: root:root
    content: |
      ${indent(6, litellm_config)}

  # --- Nginx Config ---
  - path: /opt/InsideLLM/nginx/nginx.conf
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, nginx_conf)}

  # --- TLS Certificate ---
  - path: /opt/InsideLLM/nginx/ssl/server.crt
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, tls_cert)}

  # --- TLS Private Key ---
  - path: /opt/InsideLLM/nginx/ssl/server.key
    permissions: "0600"
    owner: root:root
    content: |
      ${indent(6, tls_key)}

  # --- DLP Pipeline ---
  - path: /opt/InsideLLM/pipelines/dlp-pipeline.py
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, dlp_pipeline_py)}

  # --- Docker daemon config (log rotation) ---
  - path: /etc/docker/daemon.json
    permissions: "0644"
    owner: root:root
    content: |
      {
        "log-driver": "json-file",
        "log-opts": {
          "max-size": "10m",
          "max-file": "3"
        }
      }

  # --- Journald size limits ---
  - path: /etc/systemd/journald.conf.d/size-limit.conf
    permissions: "0644"
    owner: root:root
    content: |
      [Journal]
      SystemMaxUse=500M
      SystemKeepFree=1G
      MaxFileSec=1week

  # --- Disk monitoring script ---
  - path: /usr/local/bin/disk-monitor.sh
    permissions: "0755"
    owner: root:root
    content: |
      #!/bin/bash
      THRESHOLD=80
      USAGE=$(df / | tail -1 | awk '{print $5}' | tr -d '%')

      if [ "$USAGE" -ge "$THRESHOLD" ]; then
          logger -t disk-monitor "WARNING: Disk usage at $${USAGE}% — running cleanup"

          # Prune old journal logs
          journalctl --vacuum-time=3d 2>/dev/null

          # Prune dangling Docker images
          docker image prune -f 2>/dev/null

          # Truncate large syslog files
          for f in /var/log/syslog /var/log/kern.log; do
              if [ -f "$f" ] && [ "$(stat -c%s "$f" 2>/dev/null)" -gt 104857600 ]; then
                  truncate -s 10M "$f"
                  logger -t disk-monitor "Truncated $f"
              fi
          done

          logger -t disk-monitor "Cleanup complete. Usage now: $(df / | tail -1 | awk '{print $5}')"
      fi

  # --- Post-deploy script ---
  - path: /opt/InsideLLM/post-deploy.sh
    permissions: "0750"
    owner: root:root
    content: |
      ${indent(6, post_deploy_sh)}

# ---------------------------------------------------------------------------
# Run commands (executed in order after packages are installed)
# ---------------------------------------------------------------------------
runcmd:
  # --- Install Docker Engine ---
  - |
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    usermod -aG docker ${ssh_admin_user}

  # --- Install Supply Chain Firewall (SCFW) as pip wrapper ---
  - |
    apt-get install -y pipx python3-pip
    sudo -u ${ssh_admin_user} bash -c 'pipx ensurepath && export PATH="$HOME/.local/bin:$PATH" && pipx install scfw && scfw configure --alias-pip'

  # --- Configure log rotation and disk monitoring ---
  - |
    mkdir -p /etc/systemd/journald.conf.d
    systemctl restart systemd-journald
    (crontab -l 2>/dev/null; echo "*/15 * * * * /usr/local/bin/disk-monitor.sh") | crontab -

  # --- Configure UFW Firewall ---
  - |
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow ssh
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow 4000/tcp comment "LiteLLM Admin"
    ufw --force enable

  # --- Create required directories ---
  - mkdir -p /opt/InsideLLM/data/postgres
  - mkdir -p /opt/InsideLLM/data/redis
  - mkdir -p /opt/InsideLLM/data/open-webui
  - mkdir -p /opt/InsideLLM/data/pgadmin
  - mkdir -p /opt/InsideLLM/data/netdata
  - mkdir -p /opt/InsideLLM/pipelines

  # --- Pull images and start the stack ---
  - |
    cd /opt/InsideLLM
    docker compose pull
    docker compose up -d

  # --- Wait for services to be healthy, then run post-deploy ---
  - |
    echo "Waiting 60 seconds for containers to initialize..."
    sleep 60
    cd /opt/InsideLLM
    bash post-deploy.sh

  # --- Log completion ---
  - echo "Cloud-init provisioning complete at $(date)" >> /var/log/InsideLLM-deploy.log

# ---------------------------------------------------------------------------
# Final message
# ---------------------------------------------------------------------------
final_message: |
  Inside LLM provisioning complete.
  System uptime: $UPTIME seconds.
  Cloud-init version: $VERSION
