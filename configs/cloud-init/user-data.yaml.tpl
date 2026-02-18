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
  - path: /opt/claude-wrapper/docker-compose.yml
    permissions: "0640"
    owner: root:root
    content: |
      ${indent(6, docker_compose_yml)}

  # --- LiteLLM Config ---
  - path: /opt/claude-wrapper/litellm-config.yaml
    permissions: "0640"
    owner: root:root
    content: |
      ${indent(6, litellm_config)}

  # --- Nginx Config ---
  - path: /opt/claude-wrapper/nginx/nginx.conf
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, nginx_conf)}

  # --- TLS Certificate ---
  - path: /opt/claude-wrapper/nginx/ssl/server.crt
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, tls_cert)}

  # --- TLS Private Key ---
  - path: /opt/claude-wrapper/nginx/ssl/server.key
    permissions: "0600"
    owner: root:root
    content: |
      ${indent(6, tls_key)}

  # --- DLP Pipeline ---
  - path: /opt/claude-wrapper/pipelines/dlp-pipeline.py
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, dlp_pipeline_py)}

  # --- Post-deploy script ---
  - path: /opt/claude-wrapper/post-deploy.sh
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
  - mkdir -p /opt/claude-wrapper/data/postgres
  - mkdir -p /opt/claude-wrapper/data/redis
  - mkdir -p /opt/claude-wrapper/data/open-webui
  - mkdir -p /opt/claude-wrapper/pipelines

  # --- Pull images and start the stack ---
  - |
    cd /opt/claude-wrapper
    docker compose pull
    docker compose up -d

  # --- Wait for services to be healthy, then run post-deploy ---
  - |
    echo "Waiting 60 seconds for containers to initialize..."
    sleep 60
    cd /opt/claude-wrapper
    bash post-deploy.sh

  # --- Log completion ---
  - echo "Cloud-init provisioning complete at $(date)" >> /var/log/claude-wrapper-deploy.log

# ---------------------------------------------------------------------------
# Final message
# ---------------------------------------------------------------------------
final_message: |
  Inside LLM provisioning complete.
  System uptime: $UPTIME seconds.
  Cloud-init version: $VERSION
