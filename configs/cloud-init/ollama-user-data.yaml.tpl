#cloud-config
# =============================================================================
# Cloud-init: Debian 12 (Bookworm) provisioning for InsideLLM Ollama VM
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

# ---------------------------------------------------------------------------
# Write configuration files
# ---------------------------------------------------------------------------
write_files:
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

# ---------------------------------------------------------------------------
# Run commands
# ---------------------------------------------------------------------------
runcmd:
  # --- Install Docker Engine ---
  - |
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
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
    ufw allow 11434/tcp comment "Ollama API"
    ufw --force enable

  # --- Run Ollama container ---
  - |
    mkdir -p /opt/InsideLLM/data/ollama
    docker run -d \
      --name insidellm-ollama \
      --restart always \
      -p 11434:11434 \
      -v /opt/InsideLLM/data/ollama:/root/.ollama \
%{ if ollama_gpu ~}
      --gpus all \
%{ endif ~}
      ollama/ollama:latest

  # --- Pull models ---
  - |
    echo "Waiting for Ollama to start..."
    sleep 15
%{ for model in ollama_models ~}
    echo "Pulling ${model}..."
    docker exec insidellm-ollama ollama pull ${model} || echo "WARNING: Failed to pull ${model}"
%{ endfor ~}

  # --- Log completion ---
  - echo "Ollama VM provisioning complete at $(date)" >> /var/log/InsideLLM-ollama-deploy.log

# ---------------------------------------------------------------------------
# Final message
# ---------------------------------------------------------------------------
final_message: |
  InsideLLM Ollama VM provisioning complete.
  System uptime: $UPTIME seconds.
