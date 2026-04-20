#cloud-config
# =============================================================================
# Cloud-init: Debian 12 (Bookworm) provisioning for InsideLLM Edge Router VM
# -----------------------------------------------------------------------------
# Role: vm_role = "edge". This VM is intentionally thin — it only runs three
# containers (oauth2-proxy, openresty, keepalived) and forwards to department
# gateway backends. No LiteLLM/Postgres/Open WebUI here. The front-door router
# terminates TLS, handles SSO, and routes by OIDC "department" claim.
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
# Package Installation (edge is thin — docker + basic network tools only)
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
  - net-tools

# ---------------------------------------------------------------------------
# Write configuration files
# ---------------------------------------------------------------------------
write_files:
  # --- Edge runtime secrets / env (consumed by docker compose at `up` time) ---
  # oauth2-proxy and keepalived read from this file via env_file. The file is
  # 0600 root so unprivileged users on the host can't enumerate OIDC secrets.
  - path: /opt/InsideLLM/.env
    permissions: "0600"
    owner: root:root
    content: |
      # --- Fleet edge shared secret (match on backends) ----------------------
      FLEET_EDGE_SECRET=${fleet_edge_secret}

      # --- OIDC (for oauth2-proxy) ------------------------------------------
      OIDC_CLIENT_ID=${oidc_client_id}
      OIDC_CLIENT_SECRET=${oidc_client_secret}
      OIDC_ISSUER_URL=${oidc_issuer_url}

      # --- oauth2-proxy session encryption ----------------------------------
      # 32-byte base64 value — rotates cookies when changed.
      OAUTH2_COOKIE_SECRET=${oauth2_cookie_secret}

      # --- keepalived (VRRP) ------------------------------------------------
      VIP=${fleet_virtual_ip}
      PEER_EDGE_IPS=${peer_edge_ips}
      KEEPALIVED_PASSWORD=${keepalived_password}

      # --- Edge identity ----------------------------------------------------
      EDGE_DOMAIN=${edge_domain}
      FLEET_PRIMARY_HOST=${fleet_primary_host}

  # --- TLS cert (base64-decoded by cloud-init b64 encoding) -----------------
  - path: /opt/InsideLLM/edge/tls.crt
    permissions: "0644"
    owner: root:root
    encoding: b64
    content: ${edge_tls_cert_b64}

  - path: /opt/InsideLLM/edge/tls.key
    permissions: "0600"
    owner: root:root
    encoding: b64
    content: ${edge_tls_key_b64}

  # --- OpenResty / nginx config for the edge front door ---------------------
  - path: /opt/InsideLLM/edge/nginx.conf
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, edge_nginx_conf)}

  # --- Lua routing script (OIDC department claim -> backend) ---------------
  - path: /opt/InsideLLM/edge/routing.lua
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, edge_routing_lua)}

  # --- Routing table (rendered by Terraform from jsonencode of routes map) -
  # MVP ships a single "_default" entry pointing at the fleet primary.
  # Stream D's Render-Fleet will overwrite this with per-department routes.
  - path: /opt/InsideLLM/edge/routes.json
    permissions: "0644"
    owner: root:root
    content: |
      ${indent(6, edge_routes_json)}

  # --- Edge docker-compose (three services: oauth2-proxy, openresty, keepalived)
  - path: /opt/InsideLLM/edge-compose.yml
    permissions: "0640"
    owner: root:root
    content: |
      services:
        oauth2-proxy:
          image: quay.io/oauth2-proxy/oauth2-proxy:v7.6.0
          container_name: insidellm-oauth2-proxy
          restart: unless-stopped
          env_file:
            - /opt/InsideLLM/.env
          environment:
            OAUTH2_PROXY_PROVIDER: oidc
            OAUTH2_PROXY_CLIENT_ID: $${OIDC_CLIENT_ID}
            OAUTH2_PROXY_CLIENT_SECRET: $${OIDC_CLIENT_SECRET}
            OAUTH2_PROXY_OIDC_ISSUER_URL: $${OIDC_ISSUER_URL}
            OAUTH2_PROXY_COOKIE_SECRET: $${OAUTH2_COOKIE_SECRET}
            OAUTH2_PROXY_REDIRECT_URL: "https://$${EDGE_DOMAIN}/oauth2/callback"
            OAUTH2_PROXY_EMAIL_DOMAINS: "*"
            OAUTH2_PROXY_HTTP_ADDRESS: "0.0.0.0:4180"
            OAUTH2_PROXY_REVERSE_PROXY: "true"
            OAUTH2_PROXY_SCOPE: "openid profile email groups"
            OAUTH2_PROXY_PASS_ACCESS_TOKEN: "true"
            OAUTH2_PROXY_PASS_AUTHORIZATION_HEADER: "true"
            OAUTH2_PROXY_PASS_USER_HEADERS: "true"
            OAUTH2_PROXY_SET_XAUTHREQUEST: "true"
            OAUTH2_PROXY_SKIP_PROVIDER_BUTTON: "true"
            # Session store: Redis on the fleet primary so sessions survive
            # edge restarts and are shared between active/passive edge VMs.
            OAUTH2_PROXY_SESSION_STORE_TYPE: "redis"
            OAUTH2_PROXY_REDIS_CONNECTION_URL: "redis://$${FLEET_PRIMARY_HOST}:6379"
            OAUTH2_PROXY_COOKIE_SECURE: "true"
            OAUTH2_PROXY_COOKIE_HTTPONLY: "true"
            OAUTH2_PROXY_COOKIE_SAMESITE: "lax"
          expose:
            - "4180"
          networks:
            - edge-net

        openresty:
          image: openresty/openresty:1.25.3.1-alpine
          container_name: insidellm-openresty
          restart: unless-stopped
          depends_on:
            - oauth2-proxy
          ports:
            - "443:443"
            - "80:80"
          volumes:
            - /opt/InsideLLM/edge/nginx.conf:/usr/local/openresty/nginx/conf/nginx.conf:ro
            - /opt/InsideLLM/edge/routing.lua:/etc/nginx/routing.lua:ro
            - /opt/InsideLLM/edge/routes.json:/etc/nginx/routes.json:ro
            - /opt/InsideLLM/edge/tls.crt:/etc/nginx/tls.crt:ro
            - /opt/InsideLLM/edge/tls.key:/etc/nginx/tls.key:ro
          networks:
            - edge-net

        keepalived:
          image: osixia/keepalived:2.0.20
          container_name: insidellm-keepalived
          restart: unless-stopped
          # VRRP multicast requires host networking — bridge networking hides
          # the VRRP advertisements and the passive peer never claims the VIP.
          network_mode: host
          cap_add:
            - NET_ADMIN
            - NET_BROADCAST
            - NET_RAW
          env_file:
            - /opt/InsideLLM/.env
          environment:
            KEEPALIVED_INTERFACE: eth0
            KEEPALIVED_VIRTUAL_IPS: $${VIP}
            KEEPALIVED_UNICAST_PEERS: "#PYTHON2BASH:[$${PEER_EDGE_IPS}]"
            KEEPALIVED_PASSWORD: $${KEEPALIVED_PASSWORD}
            KEEPALIVED_PRIORITY: "100"
            KEEPALIVED_ROUTER_ID: "51"

      networks:
        edge-net:
          driver: bridge

  # --- systemd unit: bring the edge stack up on boot -----------------------
  - path: /etc/systemd/system/insidellm-edge.service
    permissions: "0644"
    owner: root:root
    content: |
      [Unit]
      Description=InsideLLM Edge Router (oauth2-proxy + openresty + keepalived)
      Requires=docker.service
      After=docker.service network-online.target
      Wants=network-online.target

      [Service]
      Type=oneshot
      RemainAfterExit=yes
      WorkingDirectory=/opt/InsideLLM
      ExecStart=/usr/bin/docker compose -f /opt/InsideLLM/edge-compose.yml up -d
      ExecStop=/usr/bin/docker compose -f /opt/InsideLLM/edge-compose.yml down
      TimeoutStartSec=300

      [Install]
      WantedBy=multi-user.target

# ---------------------------------------------------------------------------
# Run commands
# ---------------------------------------------------------------------------
runcmd:
  # --- Install Docker Engine -----------------------------------------------
  - |
    curl -fsSL https://download.docker.com/linux/debian/gpg | gpg --dearmor -o /usr/share/keyrings/docker-archive-keyring.gpg
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/docker-archive-keyring.gpg] https://download.docker.com/linux/debian $(lsb_release -cs) stable" > /etc/apt/sources.list.d/docker.list
    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin
    systemctl enable docker
    systemctl start docker
    usermod -aG docker ${ssh_admin_user}

  # --- Configure UFW firewall (edge exposes HTTPS + VRRP) ------------------
  - |
    ufw default deny incoming
    ufw default allow outgoing
    ufw allow ssh
    ufw allow 80/tcp comment "HTTP redirect"
    ufw allow 443/tcp comment "HTTPS front door"
    # VRRP multicast (protocol 112) — required for keepalived active/passive.
    ufw allow from any to 224.0.0.18 comment "VRRP multicast"
    ufw allow proto vrrp from any comment "VRRP unicast/multicast"
    ufw --force enable

  # --- Enable + start the edge stack ---------------------------------------
  - |
    systemctl daemon-reload
    systemctl enable insidellm-edge.service
    systemctl start insidellm-edge.service

  # --- Log completion ------------------------------------------------------
  - echo "Edge provisioning complete at $(date)" >> /var/log/InsideLLM-edge-deploy.log

# ---------------------------------------------------------------------------
# Final message
# ---------------------------------------------------------------------------
final_message: |
  InsideLLM Edge Router provisioning complete.
  Front door: https://${edge_domain}/
  VIP: ${fleet_virtual_ip}
  Primary backend: ${fleet_primary_host}
  System uptime: $UPTIME seconds.
