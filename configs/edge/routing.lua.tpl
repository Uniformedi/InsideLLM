-- =============================================================================
-- InsideLLM Edge Routing
-- -----------------------------------------------------------------------------
-- Picks a backend for the current request based on the user's department
-- claim (supplied by oauth2-proxy as the X-Auth-Request-Department response
-- header and captured into nginx variable $user_dept by auth_request_set).
--
-- Lookup order:
--   1. ngx.shared.routes_cache (populated at init by nginx.conf's
--      init_by_lua_block from /etc/nginx/routes.json)
--   2. Re-read /etc/nginx/routes.json on the fly (covers the case where
--      Render-Fleet replaced the file after nginx started, before a reload)
--   3. "_default" key — always required; Stream D populates real routes.
--
-- On miss (no _default + no dept match) we return 502 and log the dept so
-- the operator can diagnose. Rendered by Terraform; ${...} substitutes at
-- apply time (none used here — the file is static today but kept as .tpl
-- so future variables can be threaded through without refactoring).
-- =============================================================================

local cjson = require "cjson.safe"
local cache = ngx.shared.routes_cache

local function load_routes_from_disk()
    local f = io.open("/etc/nginx/routes.json", "r")
    if not f then
        return nil
    end
    local txt = f:read("*a")
    f:close()
    if not txt or txt == "" then
        return nil
    end
    return cjson.decode(txt)
end

local function lookup(key)
    if not key or key == "" then
        return nil
    end
    -- Fast path: shared dict.
    local v = cache:get(key)
    if v then
        return v
    end
    -- Fallback: re-read disk. Populate the cache so subsequent requests
    -- hit the fast path.
    local routes = load_routes_from_disk()
    if routes and routes[key] then
        cache:set(key, routes[key])
        return routes[key]
    end
    return nil
end

local dept = ngx.var.user_dept
if dept == nil or dept == "" then
    dept = "_default"
end

local backend = lookup(dept) or lookup("_default")

if not backend or backend == "" then
    ngx.log(ngx.ERR, "edge-routing: no backend for department '", dept, "'")
    ngx.status = ngx.HTTP_BAD_GATEWAY
    ngx.header["Content-Type"] = "text/plain"
    ngx.say("Edge: no backend configured for department: ", dept)
    return ngx.exit(ngx.HTTP_BAD_GATEWAY)
end

ngx.var.backend = backend
