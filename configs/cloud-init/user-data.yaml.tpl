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
  # --- Runtime secrets env file (Docker Compose reads this automatically) ---
  # Lives next to docker-compose.yml; `$${VAR}` tokens in that file
  # substitute from here at `docker compose up` time, so the rendered
  # compose on disk never contains the secret values.
  - path: /opt/InsideLLM/.env
    permissions: "0600"
    owner: root:root
    content: |
      ${indent(6, env_file_contents)}

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

  # --- LiteLLM Humility Prompt Callback (Layer 1: soft guidance) ---
  - path: /opt/InsideLLM/litellm-callbacks/humility_prompt.py
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, humility_callback_py)}

  # --- LiteLLM Humility Guardrail (Layer 2: hard enforcement) ---
  - path: /opt/InsideLLM/litellm-callbacks/humility_guardrail.py
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, humility_guardrail_py)}

  # --- LiteLLM DLP Guardrail (gateway-level, covers all clients) ---
  - path: /opt/InsideLLM/litellm-callbacks/dlp_guardrail.py
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, dlp_guardrail_py)}

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

  # NOTE: AI_Governance_Framework.md is no longer bundled at deploy time.
  # It's now uploaded through the admin UI (/governance on the Framework
  # tab → Upload) and stored in the central Fleet DB, so every instance
  # in a fleet sees the same authoritative version. Legacy fallback: if
  # the file happens to exist at /opt/InsideLLM/governance-hub/framework/
  # AI_Governance_Framework.md on a given host, the seed endpoint will
  # still read it when the central DB has no document.

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

%{ if ldap_enable_services ~}
  # --- Grafana LDAP configuration ---
  # Used by Grafana's native LDAP auth. Each [[servers.group_mappings]]
  # entry maps an AD group to a Grafana role; the last catch-all "*" gives
  # every authenticated user a Viewer seat.
  - path: /opt/InsideLLM/grafana/ldap.toml
    permissions: "0640"
    owner: root:root
    content: |
      [[servers]]
      host = "${ad_domain}"
      port = 636
      use_ssl = true
      start_tls = false
      ssl_skip_verify = true

      bind_dn = "${ldap_bind_dn}"
      bind_password = "${ldap_bind_password}"

      search_filter = "(sAMAccountName=%s)"
      search_base_dns = ["${ldap_user_search_base}"]

      [servers.attributes]
      name = "givenName"
      surname = "sn"
      username = "sAMAccountName"
      member_of = "memberOf"
      email = "mail"

%{ for grp in split(",", ad_admin_groups) ~}
      [[servers.group_mappings]]
      group_dn = "CN=${trimspace(grp)},CN=Users,${ldap_user_search_base}"
      org_role = "Admin"
      grafana_admin = true

%{ endfor ~}
      [[servers.group_mappings]]
      group_dn = "*"
      org_role = "Viewer"
%{ endif ~}

%{ if length(dc_dns_servers) > 0 ~}
  # --- Domain controller DNS (required for LDAP admin auth) ---
  # Netplan drop-in: overrides DHCP-provided DNS with the AD DCs so
  # uniformedi.local (and other domain names) resolve. Without this the
  # Governance Hub's ldap_authenticate() can't find the DC and admin
  # login silently fails.
  - path: /etc/netplan/99-insidellm-dns.yaml
    permissions: "0600"
    owner: root:root
    content: |
      network:
        version: 2
        ethernets:
          eth0:
            nameservers:
              addresses: [${join(", ", dc_dns_servers)}]
              search: [${ad_domain}]
            dhcp4-overrides:
              use-dns: false
%{ endif ~}

  # --- Journald size limits ---
  - path: /etc/systemd/journald.conf.d/size-limit.conf
    permissions: "0644"
    owner: root:root
    content: |
      [Journal]
      SystemMaxUse=500M
      SystemKeepFree=1G
      MaxFileSec=1week

  # --- AD realm-join runner (host-side; triggered by Governance Hub) ---
  - path: /opt/InsideLLM/scripts/ad-join-runner.sh
    permissions: "0750"
    owner: root:root
    content: |
      ${indent(6, ad_join_runner_sh)}

  # --- systemd path watcher: fires the runner when the request file appears ---
  - path: /etc/systemd/system/insidellm-ad-join.path
    permissions: "0644"
    owner: root:root
    content: |
      [Unit]
      Description=Watch for InsideLLM AD-join requests
      [Path]
      PathExists=/opt/InsideLLM/ad-join-request.json
      [Install]
      WantedBy=multi-user.target

  - path: /etc/systemd/system/insidellm-ad-join.service
    permissions: "0644"
    owner: root:root
    content: |
      [Unit]
      Description=Process an InsideLLM AD-join request
      ConditionPathExists=/opt/InsideLLM/ad-join-request.json
      [Service]
      Type=oneshot
      ExecStart=/opt/InsideLLM/scripts/ad-join-runner.sh
      User=root

  # --- Open WebUI service-account provisioner (invoked by post-deploy.sh) ---
  - path: /opt/InsideLLM/scripts/provision-owui-service-account.sh
    permissions: "0755"
    owner: root:root
    content: |
      ${indent(6, provision_owui_svc_sh)}

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
  # Grafana scans /etc/grafana/provisioning/{datasources,dashboards,...}/
  # for *.yaml. The yaml files MUST live inside their typed subdirectory;
  # putting them directly under provisioning/ makes Grafana log
  # "no such file or directory" and silently provision nothing.
  - path: /opt/InsideLLM/grafana/provisioning/datasources/datasources.yml
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, grafana_datasources_yml)}

  # --- Grafana dashboard provisioning ---
  - path: /opt/InsideLLM/grafana/provisioning/dashboards/dashboards.yml
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
%{ if length(dc_dns_servers) > 0 ~}
  # --- Apply DC DNS override (must run before any domain lookup) ---
  - chmod 0600 /etc/netplan/99-insidellm-dns.yaml
  - netplan apply
  - sleep 2
%{ endif ~}

%{ if cockpit_enable ~}
  # --- Install Cockpit (per-VM Linux web management) ---
  # Lightweight Linux equivalent of Windows Admin Center: web shell,
  # service control, log viewer, container management. Runs on host
  # port 9090; nginx exposes it at /cockpit/ inside the same TLS cert.
  #
  # PAM: Ubuntu's default /etc/pam.d/cockpit includes common-auth, which
  # gets pam_sss.so injected automatically when `realm join` runs (see the
  # Governance Hub AD-integration form). So SSSD-backed AD logins work
  # post-join with zero extra configuration here.
  - |
    apt-get update
    apt-get install -y --no-install-recommends cockpit cockpit-podman cockpit-storaged
    # Tell Cockpit it is being reverse-proxied so absolute redirects work
    # behind the InsideLLM nginx.
    install -d -m 0755 /etc/cockpit
    cat > /etc/cockpit/cockpit.conf <<COCKPITEOF
    [WebService]
    AllowUnencrypted = true
    Origins = https://${fqdn} wss://${fqdn} http://localhost
    UrlRoot = /cockpit/
    ProtocolHeader = X-Forwarded-Proto
    ForwardedForHeader = X-Forwarded-For
    LoginTitle = InsideLLM ${vm_hostname}
    COCKPITEOF
    # Restrict Cockpit login to local admins + members of ad_admin_groups.
    # pam_access reads /etc/security/access.conf.d/cockpit-insidellm.conf
    # (order matters: first match wins).
    install -d -m 0755 /etc/security/access.conf.d
    cat > /etc/security/access.conf.d/cockpit-insidellm.conf <<ACCESSEOF
    # InsideLLM Cockpit access policy. Permit the local admin user and
    # members of the configured AD admin groups; deny everything else.
    + : ${ssh_admin_user} : ALL
%{ for grp in split(",", ad_admin_groups) ~}
    + : (${trimspace(grp)}) : ALL
%{ endfor ~}
    - : ALL : ALL
    ACCESSEOF
    # Wire pam_access into the Cockpit PAM stack (not applied by default).
    if ! grep -q "pam_access.so" /etc/pam.d/cockpit 2>/dev/null; then
      sed -i '/^auth\s/i account    required     pam_access.so accessfile=/etc/security/access.conf.d/cockpit-insidellm.conf' /etc/pam.d/cockpit 2>/dev/null || true
    fi
    systemctl daemon-reload
    systemctl enable cockpit.socket
    systemctl restart cockpit.socket
%{ endif ~}

  # --- Install Docker Engine ---
  - |
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/ubuntu $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    usermod -aG docker ${ssh_admin_user}

  # --- AD-integration prerequisites ---
  # Packages needed for `realm join`. Install regardless of ad_domain_join
  # so the Governance Hub form can trigger a join later without redeploy.
  - |
    DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      realmd sssd sssd-tools adcli samba-common-bin oddjob oddjob-mkhomedir \
      packagekit jq libnss-sss libpam-sss krb5-user
    systemctl enable --now insidellm-ad-join.path

  # --- Install Supply Chain Firewall (SCFW) as pip wrapper ---
  - |
    apt-get install -y pipx python3-pip
    sudo -u ${ssh_admin_user} bash -c 'pipx ensurepath && export PATH="$HOME/.local/bin:$PATH" && pipx install scfw && scfw configure --alias-pip'

  # --- Configure log rotation and disk monitoring ---
  - |
    mkdir -p /etc/systemd/journald.conf.d
    systemctl restart systemd-journald
    CRON_TMP=$(mktemp)
    crontab -l 2>/dev/null > "$CRON_TMP" || true
    printf '%%s\n' "*/15 * * * * /usr/local/bin/disk-monitor.sh" >> "$CRON_TMP"
%{ if ops_backup_schedule == "daily" ~}
    printf '%%s\n' "0 2 * * * /opt/InsideLLM/backup-postgres.sh" >> "$CRON_TMP"
%{ endif ~}
%{ if ops_backup_schedule == "weekly" ~}
    printf '%%s\n' "0 2 * * 0 /opt/InsideLLM/backup-postgres.sh" >> "$CRON_TMP"
%{ endif ~}
%{ if ops_trivy_enable ~}
    printf '%%s\n' "0 5 * * * /opt/InsideLLM/trivy-scan.sh" >> "$CRON_TMP"
%{ endif ~}
    printf '%%s\n' "*/15 * * * * docker exec insidellm-postgres psql -U litellm -d litellm -c 'SELECT refresh_keyword_views()' > /dev/null 2>&1" >> "$CRON_TMP"
    crontab "$CRON_TMP"
    rm -f "$CRON_TMP"

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
    ufw allow 5050/tcp comment "pgAdmin"
%{ if ollama_enable ~}
    ufw allow 11434/tcp comment "Ollama API"
%{ endif ~}
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
      nsupdate -g <<DNSEOF 2>> /var/log/InsideLLM-deploy.log || true
    server $DNS_SERVER
    zone $DOMAIN
    update delete $HOSTNAME.$DOMAIN. A
    update add $HOSTNAME.$DOMAIN. 3600 A $VM_IP
    send
    DNSEOF

      # Also register a PTR record if possible
      IP_REVERSE=$(echo "$VM_IP" | awk -F. '{print $4"."$3"."$2"."$1}')
      nsupdate -g <<PTREOF 2>> /var/log/InsideLLM-deploy.log || true
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
  - mkdir -p /opt/InsideLLM/ad-join
  - chmod 0750 /opt/InsideLLM/ad-join
  - chown 999:999 /opt/InsideLLM/ad-join  # govhub UID inside the container
  - mkdir -p /opt/InsideLLM/data/pgadmin
  # pgAdmin runs as UID 5050 inside its container; without this chown
  # workers crash on /var/lib/pgadmin/sessions creation, gunicorn keeps
  # respawning, container reports 'Up' but never serves HTTP.
  - chown -R 5050:5050 /opt/InsideLLM/data/pgadmin
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
