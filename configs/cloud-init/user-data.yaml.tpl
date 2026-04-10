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
  # Ubuntu Desktop Experience
  - ubuntu-desktop-minimal
  - xrdp
%{ if ad_domain_join ~}
  # Active Directory domain join
  - realmd
  - sssd
  - sssd-tools
  - adcli
  - krb5-user
  - samba-common-bin
  - packagekit
  - libnss-sss
  - libpam-sss
  - dnsutils
%{ endif ~}

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

  # --- Admin Portal ---
  - path: /opt/InsideLLM/admin.html
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, admin_html)}

  # --- Setup Wizard (used for clone-to-wizard flow) ---
  - path: /opt/InsideLLM/Setup.html
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, setup_html)}

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

%{ if docforge_enable ~}
  # --- DocForge source archive ---
  - path: /opt/InsideLLM/docforge.zip
    permissions: "0644"
    owner: root:root
    encoding: b64
    content: ${docforge_zip_b64}

  # --- DocForge Open WebUI Tool ---
  - path: /opt/InsideLLM/pipelines/docforge-tool.py
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, docforge_tool_py)}
%{ endif ~}

%{ if policy_engine_enable ~}
  # --- OPA policies archive ---
  - path: /opt/InsideLLM/opa-policies.zip
    permissions: "0644"
    owner: root:root
    encoding: b64
    content: ${opa_zip_b64}

  # --- OPA Policy Enforcement Pipeline ---
  - path: /opt/InsideLLM/pipelines/opa-policy-pipeline.py
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, opa_policy_pipeline_py)}
%{ endif ~}

%{ if governance_hub_enable ~}
  # --- Governance Hub source archive ---
  - path: /opt/InsideLLM/governance-hub.zip
    permissions: "0644"
    owner: root:root
    encoding: b64
    content: ${governance_hub_zip_b64}

  # --- Governance Advisor Open WebUI Tool ---
  - path: /opt/InsideLLM/pipelines/governance-advisor-tool.py
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, governance_advisor_tool_py)}

  # --- Fleet Management Open WebUI Tool ---
  - path: /opt/InsideLLM/pipelines/fleet-management-tool.py
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, fleet_management_tool_py)}

  # --- AI System Designer Open WebUI Tool ---
  - path: /opt/InsideLLM/pipelines/system-designer-tool.py
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, system_designer_tool_py)}

  # --- Data Connector Open WebUI Tool ---
  - path: /opt/InsideLLM/pipelines/data-connector-tool.py
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, data_connector_tool_py)}
%{ endif ~}

%{ if ops_grafana_enable ~}
  # --- Loki config ---
  - path: /opt/InsideLLM/loki/loki-config.yml
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, loki_config)}

  # --- Promtail config ---
  - path: /opt/InsideLLM/promtail/promtail-config.yml
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, promtail_config)}

  # --- Grafana datasources ---
  - path: /opt/InsideLLM/grafana/provisioning/datasources.yml
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, grafana_datasources_yml)}

  # --- Grafana dashboard provisioning ---
  - path: /opt/InsideLLM/grafana/provisioning/dashboards.yml
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, grafana_dashboards_yml)}

  # --- Grafana compliance dashboard ---
  - path: /opt/InsideLLM/grafana/dashboards/compliance.json
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, grafana_compliance_json)}

%{ if grafana_fleet_json != "" ~}
  # --- Grafana fleet management dashboard ---
  - path: /opt/InsideLLM/grafana/dashboards/fleet.json
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, grafana_fleet_json)}
%{ endif ~}
%{ endif ~}

%{ if ops_trivy_enable ~}
  # --- Trivy CVE scan script ---
  - path: /opt/InsideLLM/trivy-scan.sh
    permissions: "0755"
    owner: root:root
    content: |
      ${indent(6, trivy_scan_sh)}
%{ endif ~}

%{ if ops_backup_schedule != "none" ~}
  # --- PostgreSQL backup script ---
  - path: /opt/InsideLLM/backup-postgres.sh
    permissions: "0755"
    owner: root:root
    content: |
      #!/bin/bash
      set -euo pipefail
      BACKUP_DIR="/opt/InsideLLM/data/backups"
      mkdir -p "$BACKUP_DIR"
      DATE=$(date +%Y-%m-%d_%H%M)
      docker exec insidellm-postgres pg_dump -U litellm -d litellm | gzip > "$BACKUP_DIR/litellm-$DATE.sql.gz"
      echo "[$(date)] Backup created: litellm-$DATE.sql.gz" >> /var/log/InsideLLM-deploy.log
      # Retain last 30 backups
      ls -t "$BACKUP_DIR"/litellm-*.sql.gz | tail -n +31 | xargs -r rm --
%{ endif ~}

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
    CRON_ENTRIES="*/15 * * * * /usr/local/bin/disk-monitor.sh"
%{ if ops_backup_schedule == "daily" ~}
    CRON_ENTRIES="$CRON_ENTRIES\n0 2 * * * /opt/InsideLLM/backup-postgres.sh"
%{ endif ~}
%{ if ops_backup_schedule == "weekly" ~}
    CRON_ENTRIES="$CRON_ENTRIES\n0 2 * * 0 /opt/InsideLLM/backup-postgres.sh"
%{ endif ~}
%{ if ops_trivy_enable ~}
    CRON_ENTRIES="$CRON_ENTRIES\n0 5 * * * /opt/InsideLLM/trivy-scan.sh"
%{ endif ~}
    CRON_ENTRIES="$CRON_ENTRIES\n*/15 * * * * docker exec insidellm-postgres psql -U litellm -d litellm -c 'SELECT refresh_keyword_views()' > /dev/null 2>&1"
    (crontab -l 2>/dev/null; echo -e "$CRON_ENTRIES") | crontab -

  # --- Configure xrdp for Remote Desktop ---
  - |
    systemctl enable xrdp
    systemctl start xrdp
    # Allow the admin user to log in via RDP
    echo "${ssh_admin_user}" | tee -a /etc/xrdp/sesman.ini > /dev/null
    # Set a password for RDP login (SSH key-only user needs one for xrdp)
    echo "${ssh_admin_user}:${xrdp_password}" | chpasswd
    sed -i 's/^lock_passwd: true/lock_passwd: false/' /etc/cloud/cloud.cfg.d/*.cfg 2>/dev/null || true

  # --- Configure UFW Firewall ---
  - |
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow ssh
    ufw allow 80/tcp
    ufw allow 443/tcp
    ufw allow 3389/tcp comment "xRDP"
    ufw allow 4000/tcp comment "LiteLLM Admin"
    ufw --force enable

%{ if ad_domain_join ~}
  # --- Join Active Directory Domain ---
  - |
    DOMAIN="${vm_domain}"
    DOMAIN_UPPER=$(echo "$DOMAIN" | tr '[:lower:]' '[:upper:]')
    JOIN_USER="${ad_join_user}"
    JOIN_PASS="${ad_join_password}"
    JOIN_OU="${ad_join_ou}"
    HOSTNAME=$(hostname)

    echo "Joining domain: $DOMAIN"

    # Configure Kerberos
    cat > /etc/krb5.conf << KRBEOF
    [libdefaults]
      default_realm = $DOMAIN_UPPER
      dns_lookup_realm = true
      dns_lookup_kdc = true
      ticket_lifetime = 24h
      renew_lifetime = 7d
      forwardable = true
      rdns = false
    [realms]
      $DOMAIN_UPPER = {
        admin_server = $DOMAIN
      }
    [domain_realm]
      .$DOMAIN = $DOMAIN_UPPER
      $DOMAIN = $DOMAIN_UPPER
    KRBEOF

    # Discover and join the domain
    realm discover "$DOMAIN" >> /var/log/InsideLLM-deploy.log 2>&1 || true

    if [ -n "$JOIN_USER" ] && [ -n "$JOIN_PASS" ]; then
      JOIN_ARGS="--user=$JOIN_USER"
      if [ -n "$JOIN_OU" ]; then
        JOIN_ARGS="$JOIN_ARGS --computer-ou=$JOIN_OU"
      fi
      echo "$JOIN_PASS" | realm join $JOIN_ARGS "$DOMAIN" >> /var/log/InsideLLM-deploy.log 2>&1
      if [ $? -eq 0 ]; then
        echo "[$(date)] Successfully joined domain $DOMAIN" >> /var/log/InsideLLM-deploy.log

        # Configure SSSD for AD authentication
        sed -i 's/use_fully_qualified_names = True/use_fully_qualified_names = False/' /etc/sssd/sssd.conf 2>/dev/null || true
        sed -i 's|fallback_homedir = /home/%u@%d|fallback_homedir = /home/%u|' /etc/sssd/sssd.conf 2>/dev/null || true
        systemctl restart sssd 2>/dev/null || true

        # Allow AD users to log in
        realm permit --all >> /var/log/InsideLLM-deploy.log 2>&1 || true

        echo "[$(date)] AD domain join complete. AD users can now SSH and RDP." >> /var/log/InsideLLM-deploy.log
      else
        echo "[$(date)] WARNING: Failed to join domain $DOMAIN" >> /var/log/InsideLLM-deploy.log
      fi
    else
      echo "[$(date)] WARNING: AD join credentials not provided. Skipping domain join." >> /var/log/InsideLLM-deploy.log
    fi

%{ if ad_dns_register ~}
    # Register hostname in AD DNS via dynamic update
    VM_IP=$(hostname -I | awk '{print $1}')
    DNS_SERVER=$(grep -m1 nameserver /etc/resolv.conf | awk '{print $2}')

    if [ -n "$VM_IP" ] && [ -n "$DNS_SERVER" ] && [ -n "$JOIN_USER" ]; then
      echo "[$(date)] Registering $HOSTNAME.$DOMAIN ($VM_IP) in DNS at $DNS_SERVER" >> /var/log/InsideLLM-deploy.log

      # Get a Kerberos ticket for DNS update
      echo "$JOIN_PASS" | kinit "$JOIN_USER@$DOMAIN_UPPER" 2>/dev/null

      # Dynamic DNS update
      nsupdate -g << DNSEOF 2>> /var/log/InsideLLM-deploy.log || true
      server $DNS_SERVER
      zone $DOMAIN
      update delete $HOSTNAME.$DOMAIN. A
      update add $HOSTNAME.$DOMAIN. 3600 A $VM_IP
      send
      DNSEOF

      # Also register a PTR record if possible
      IP_REVERSE=$(echo "$VM_IP" | awk -F. '{print $4"."$3"."$2"."$1}')
      nsupdate -g << PTREOF 2>> /var/log/InsideLLM-deploy.log || true
      server $DNS_SERVER
      update delete $IP_REVERSE.in-addr.arpa. PTR
      update add $IP_REVERSE.in-addr.arpa. 3600 PTR $HOSTNAME.$DOMAIN.
      send
      PTREOF

      kdestroy 2>/dev/null || true
      echo "[$(date)] DNS registration complete" >> /var/log/InsideLLM-deploy.log
    else
      echo "[$(date)] WARNING: Skipping DNS registration (missing IP, DNS server, or credentials)" >> /var/log/InsideLLM-deploy.log
    fi
%{ endif ~}
%{ endif ~}

  # --- Create required directories ---
  - mkdir -p /opt/InsideLLM/data/postgres
  - mkdir -p /opt/InsideLLM/data/redis
  - mkdir -p /opt/InsideLLM/data/open-webui
  - mkdir -p /opt/InsideLLM/data/pgadmin
  - mkdir -p /opt/InsideLLM/data/netdata
  - mkdir -p /opt/InsideLLM/pipelines
%{ if ops_grafana_enable ~}
  - mkdir -p /opt/InsideLLM/data/grafana
  - mkdir -p /opt/InsideLLM/data/loki
  - chown 472:472 /opt/InsideLLM/data/grafana
  - chown 10001:10001 /opt/InsideLLM/data/loki
%{ endif ~}
%{ if ops_uptime_kuma_enable ~}
  - mkdir -p /opt/InsideLLM/data/uptime-kuma
%{ endif ~}
%{ if ops_backup_schedule != "none" ~}
  - mkdir -p /opt/InsideLLM/data/backups
%{ endif ~}
%{ if ops_trivy_enable ~}
  - mkdir -p /opt/InsideLLM/data/trivy-reports
%{ endif ~}
%{ if policy_engine_enable ~}
  - mkdir -p /opt/InsideLLM/opa/policies
  - |
    cd /opt/InsideLLM
    if [ ! -s opa-policies.zip ]; then
      echo "ERROR: opa-policies.zip is empty or missing" >&2
      exit 1
    fi
    unzip -o opa-policies.zip -d opa
    rm -f opa-policies.zip
%{ endif ~}
%{ if governance_hub_enable ~}
  - mkdir -p /opt/InsideLLM/data/governance-hub && chown 999:999 /opt/InsideLLM/data/governance-hub
  - |
    # Store deployment tfvars (base64-encoded) for governance-hub to encrypt on startup
    echo "${deployment_tfvars_b64}" | base64 -d > /opt/InsideLLM/data/governance-hub/.deployment-tfvars-pending
    chown 999:999 /opt/InsideLLM/data/governance-hub/.deployment-tfvars-pending
    chmod 600 /opt/InsideLLM/data/governance-hub/.deployment-tfvars-pending
  - |
    cd /opt/InsideLLM
    if [ ! -s governance-hub.zip ]; then
      echo "ERROR: governance-hub.zip is empty or missing" >&2
      exit 1
    fi
    unzip -o governance-hub.zip -d governance-hub
    rm -f governance-hub.zip
%{ endif ~}
%{ if docforge_enable ~}
  - mkdir -p /opt/InsideLLM/data/docforge/temp
  - |
    cd /opt/InsideLLM
    if [ ! -s docforge.zip ]; then
      echo "ERROR: docforge.zip is empty or missing" >&2
      exit 1
    fi
    unzip -o docforge.zip -d docforge
    rm -f docforge.zip
%{ endif ~}

  # --- Pull images, build local images, and start the stack ---
  - |
    cd /opt/InsideLLM
    docker compose pull --ignore-buildable
    docker compose build
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
