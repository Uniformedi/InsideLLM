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
            proxy_pass http://litellm/;
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

        # --- Health check ---
        location /nginx-health {
            return 200 'OK';
            add_header Content-Type text/plain;
        }
    }
}
