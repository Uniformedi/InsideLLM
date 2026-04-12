# =============================================================================
# Nginx: Reverse proxy for Inside LLM
# Managed by Terraform
# =============================================================================

worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /var/run/nginx.pid;

events {
    worker_connections 1024;
}

http {
    include       /etc/nginx/mime.types;
    default_type  application/octet-stream;

    # --- Logging ---
    log_format main '$remote_addr - $remote_user [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent"';
    access_log /var/log/nginx/access.log main;

    # --- Performance ---
    sendfile        on;
    tcp_nopush      on;
    tcp_nodelay     on;
    keepalive_timeout 65;
    types_hash_max_size 2048;
    client_max_body_size 50m;

    # --- Security headers ---
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-XSS-Protection "1; mode=block" always;
    add_header Referrer-Policy "strict-origin-when-cross-origin" always;
    add_header Strict-Transport-Security "max-age=31536000; includeSubDomains" always;

    # --- Upstreams ---
    upstream open-webui {
        server open-webui:8080;
    }

    upstream litellm {
        server litellm:4000;
    }

    upstream netdata {
        server netdata:19999;
    }
%{ if docforge_enable ~}

    upstream docforge {
        server docforge:3000;
    }
%{ endif ~}
%{ if governance_hub_enable ~}

    upstream governance-hub {
        server governance-hub:8090;
    }
%{ endif ~}
%{ if ops_grafana_enable ~}

    upstream grafana {
        server grafana:3000;
    }
%{ endif ~}
%{ if ops_uptime_kuma_enable ~}

    upstream uptime-kuma {
        server uptime-kuma:3001;
    }
%{ endif ~}

    # --- HTTP -> HTTPS redirect ---
    server {
        listen 80;
        server_name ${server_name} ${vm_hostname} _;

        location /health {
            return 200 'OK';
            add_header Content-Type text/plain;
        }

        location / {
            return 301 https://$host$request_uri;
        }
    }

    # --- HTTPS server ---
    server {
        listen 443 ssl;
        http2 on;
        server_name ${server_name} ${vm_hostname} _;

        # --- TLS ---
        ssl_certificate     /etc/nginx/ssl/server.crt;
        ssl_certificate_key /etc/nginx/ssl/server.key;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_ciphers         HIGH:!aNULL:!MD5;
        ssl_prefer_server_ciphers on;
        ssl_session_cache   shared:SSL:10m;
        ssl_session_timeout 1d;

        # --- Open WebUI (default route) ---
        location / {
            proxy_pass http://open-webui;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_buffering off;
            proxy_read_timeout 300s;
            proxy_connect_timeout 75s;
        }

        # --- LiteLLM Proxy API ---
        # Direct API access for Claude Code CLI and other API consumers
        location /litellm/ {
            proxy_pass http://litellm;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_buffering off;
            proxy_read_timeout 300s;
        }

        # --- LiteLLM UI static assets ---
        # Next.js dashboard uses assetPrefix "/litellm-asset-prefix"
        location /litellm-asset-prefix/ {
            proxy_pass http://litellm/litellm-asset-prefix/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # --- LiteLLM OpenAI-compatible endpoint ---
        # For Claude Code: ANTHROPIC_BASE_URL=https://host/v1
        location /v1/ {
            proxy_pass http://litellm/v1/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_buffering off;
            proxy_read_timeout 300s;
        }

        # --- Netdata Monitoring Dashboard ---
        location /netdata/ {
            proxy_pass http://netdata/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_buffering off;
        }

%{ if docforge_enable ~}
        # --- DocForge File Conversion API ---
        location /docforge/ {
            proxy_pass http://docforge/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_buffering off;
            proxy_read_timeout 120s;
            client_max_body_size ${docforge_max_body_size}m;
        }

%{ endif ~}
%{ if governance_hub_enable ~}
        # --- Governance Hub API ---
        location /governance/ {
            proxy_pass http://governance-hub/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_buffering off;
            proxy_read_timeout 180s;
        }

%{ endif ~}
%{ if ops_grafana_enable ~}
        # --- Grafana Compliance Dashboard ---
        location /grafana/ {
            proxy_pass http://grafana;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_buffering off;
        }

%{ endif ~}
%{ if ops_uptime_kuma_enable ~}
        # --- Uptime Kuma Service Monitoring ---
        # Uptime Kuma serves assets/socket.io from absolute root paths, so we
        # both rewrite HTML refs (sub_filter) and expose the absolute paths it
        # expects (/assets/, /socket.io/, /icon.svg, etc.) under the same upstream.
        location /status/ {
            proxy_pass http://uptime-kuma/;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            proxy_buffering off;
            proxy_redirect / /status/;

            # Rewrite absolute asset/api references in HTML so the browser
            # requests them under /status/... instead of the nginx root.
            sub_filter_once off;
            sub_filter_types text/html application/javascript;
            sub_filter 'href="/'   'href="/status/';
            sub_filter 'src="/'    'src="/status/';
            sub_filter '"/assets/' '"/status/assets/';
            sub_filter '"/socket.io' '"/status/socket.io';
        }

        # Uptime Kuma websocket + assets at absolute paths (fallback for clients
        # that didn't pick up the rewritten HTML, e.g. status page bookmarks).
        location /assets/ {
            proxy_pass http://uptime-kuma;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
        }
        location /socket.io/ {
            proxy_pass http://uptime-kuma;
            proxy_http_version 1.1;
            proxy_set_header Upgrade $http_upgrade;
            proxy_set_header Connection "upgrade";
            proxy_set_header Host $host;
            proxy_read_timeout 86400s;
        }

%{ endif ~}
%{ if admin_auth_mode != "none" ~}
        # --- Auth subrequest target ---
        location = /auth/validate {
            internal;
            proxy_pass http://governance-hub:8090/auth/validate;
            proxy_pass_request_body off;
            proxy_set_header Content-Length "";
            proxy_set_header X-Original-URI $request_uri;
            proxy_set_header Cookie $http_cookie;
        }

        # --- Auth endpoints (login, callback, logout, whoami) ---
        location /auth/ {
            proxy_pass http://governance-hub:8090/auth/;
            proxy_http_version 1.1;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
%{ endif ~}

        # --- Admin Portal ---
        location /admin {
%{ if admin_auth_mode != "none" ~}
            auth_request /auth/validate;
            error_page 401 = /auth/login;
%{ endif ~}
            alias /opt/InsideLLM/admin.html;
            default_type text/html;
        }

        # --- Setup Wizard (used for cloning) ---
        location /setup {
            alias /opt/InsideLLM/Setup.html;
            default_type text/html;
        }

        # --- Health check ---
        location = /nginx-health {
            access_log off;
            default_type text/plain;
            return 200 "OK\n";
        }
    }
}
