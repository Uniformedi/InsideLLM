# =============================================================================
# OpenResty: InsideLLM Edge Front Door
# -----------------------------------------------------------------------------
# Terminates TLS for ${edge_domain}, runs OIDC subrequest auth via oauth2-proxy,
# and proxies to department gateway backends chosen by routing.lua from the
# X-Auth-Request-Department claim. Rendered by Terraform; $${...} tokens are
# substituted at apply time.
# =============================================================================

worker_processes auto;
error_log /var/log/nginx/error.log warn;
pid /run/openresty.pid;

events {
    worker_connections 2048;
}

http {
    include       mime.types;
    default_type  application/octet-stream;

    # --- Logging ---
    log_format edge '$remote_addr - $user_email [$time_local] '
                    '"$request" $status $body_bytes_sent '
                    '"$http_referer" "$http_user_agent" '
                    'dept=$user_dept backend=$backend';
    access_log /var/log/nginx/access.log edge;

    # --- Performance ---
    sendfile        on;
    tcp_nopush      on;
    tcp_nodelay     on;
    keepalive_timeout 65;
    client_max_body_size 50m;

    # --- Shared dict for cached routing table (populated on init, refreshed
    #     on SIGHUP when Render-Fleet replaces /etc/nginx/routes.json). ---
    lua_shared_dict routes_cache 1m;
    lua_package_path "/etc/nginx/?.lua;;";

    # --- WebSocket upgrade map ---
    map $http_upgrade $http_connection {
        default upgrade;
        ''      close;
    }

    # --- Load routes.json into the shared dict once at init time. If the
    #     file is missing or malformed, we fall back to per-request reads in
    #     routing.lua so the edge still boots. ---
    init_by_lua_block {
        local cjson = require "cjson.safe"
        local f = io.open("/etc/nginx/routes.json", "r")
        if f then
            local txt = f:read("*a")
            f:close()
            local parsed = cjson.decode(txt)
            if parsed then
                for k, v in pairs(parsed) do
                    ngx.shared.routes_cache:set(k, v)
                end
            end
        end
    }

    # --- HTTP -> HTTPS redirect ---
    server {
        listen 80;
        server_name ${edge_domain} _;

        location = /health {
            return 200 'OK';
            add_header Content-Type text/plain;
        }

        location / {
            return 301 https://$host$request_uri;
        }
    }

    # --- HTTPS front door ---
    server {
        listen 443 ssl;
        http2 on;
        server_name ${edge_domain} _;

        ssl_certificate     /etc/nginx/tls.crt;
        ssl_certificate_key /etc/nginx/tls.key;
        ssl_protocols       TLSv1.2 TLSv1.3;
        ssl_ciphers         HIGH:!aNULL:!MD5;
        ssl_prefer_server_ciphers on;
        ssl_session_cache   shared:SSL:10m;
        ssl_session_timeout 1d;

        # --- oauth2-proxy browser-facing routes (login page, callback, logout)
        location /oauth2/ {
            proxy_pass       http://oauth2-proxy:4180;
            proxy_set_header Host                    $host;
            proxy_set_header X-Real-IP               $remote_addr;
            proxy_set_header X-Forwarded-For         $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto       $scheme;
            proxy_set_header X-Auth-Request-Redirect $request_uri;
        }

        # --- Internal subrequest target for auth_request ---
        # nginx issues a GET to this location per request. oauth2-proxy
        # returns 202 if a valid session cookie is present (and emits
        # X-Auth-Request-* response headers we capture below) or 401
        # otherwise, which triggers the error_page redirect to /oauth2/start.
        location = /oauth2/auth {
            internal;
            proxy_pass       http://oauth2-proxy:4180/oauth2/auth;
            proxy_set_header Host             $host;
            proxy_set_header X-Real-IP        $remote_addr;
            proxy_set_header X-Forwarded-Uri  $request_uri;
            # The auth subrequest should never send a body.
            proxy_pass_request_body off;
            proxy_set_header Content-Length "";
        }

        # --- Convenience: kick off the OIDC dance ---
        location = /oauth2/start {
            return 302 /oauth2/sign_in?rd=$scheme://$host$request_uri;
        }

        # --- Health check (no auth, no routing) ---
        location = /edge-health {
            access_log off;
            default_type text/plain;
            return 200 "OK\n";
        }

        # --- Default location: authenticated + routed by department ---
        location / {
            auth_request /oauth2/auth;

            # Capture identity headers returned by oauth2-proxy and expose
            # them as nginx variables so proxy_set_header below can forward
            # them to backends (edge secret establishes trust).
            auth_request_set $user_email   $upstream_http_x_auth_request_email;
            auth_request_set $user_dept    $upstream_http_x_auth_request_department;
            auth_request_set $user_groups  $upstream_http_x_auth_request_groups;
            auth_request_set $user_pref    $upstream_http_x_auth_request_preferred_username;

            error_page 401 = /oauth2/start;

            # Backend hostname/IP selected by routing.lua from the dept claim.
            set $backend "";
            access_by_lua_file /etc/nginx/routing.lua;

            # Forward to department gateway over TLS. Backends verify the
            # X-Edge-Secret header before trusting X-User-* claims (see
            # the main nginx.conf.tpl map in the primary stack).
            proxy_pass         https://$backend;
            proxy_ssl_verify   off;
            proxy_http_version 1.1;
            proxy_set_header   Host                 $host;
            proxy_set_header   X-Real-IP            $remote_addr;
            proxy_set_header   X-Forwarded-For      $proxy_add_x_forwarded_for;
            proxy_set_header   X-Forwarded-Proto    $scheme;
            proxy_set_header   Upgrade              $http_upgrade;
            proxy_set_header   Connection           $http_connection;

            # Edge trust handshake — backends gate on matching secret.
            proxy_set_header   X-Edge-Secret        "${fleet_edge_secret}";
            proxy_set_header   X-User-Email         $user_email;
            proxy_set_header   X-User-Department    $user_dept;
            proxy_set_header   X-User-Groups        $user_groups;
            proxy_set_header   X-User-Preferred     $user_pref;

            proxy_buffering    off;
            proxy_read_timeout 300s;
            proxy_connect_timeout 75s;
        }
    }
}
