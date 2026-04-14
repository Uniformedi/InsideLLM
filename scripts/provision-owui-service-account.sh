#!/usr/bin/env bash
# provision-owui-service-account.sh
#
# Create a dedicated Open WebUI local account used ONLY by the
# Governance Hub's skill-sync bridge, generate its API key, and write
# the key to /opt/InsideLLM/.env so docker-compose interpolates it into
# the governance-hub container.
#
# Why a service account instead of a human admin's key:
#   - Model create/delete events attribute to the service account, not a
#     human user, which keeps OWUI's audit trail machine-vs-human-clean.
#   - The account survives human identity changes (password rotation,
#     offboarding, AD moves).
#   - At fleet scale, each instance provisions its own service account so
#     cross-instance audit logs attribute to governance-hub-<instance>.
#
# Idempotent: skipping with exit 0 if OPEN_WEBUI_API_KEY already exists
# in the env file. Safe to re-run.
#
# Called from post-deploy.sh after Open WebUI is healthy. Can also be run
# by hand: `sudo bash scripts/provision-owui-service-account.sh`

set -euo pipefail

ENV_FILE="${ENV_FILE:-/opt/InsideLLM/.env}"
# INSTANCE_ID should come from the caller (post-deploy.sh renders it from
# Terraform's var.vm_name). Fall back to the machine's hostname so an ad-hoc
# run of the script still produces a disambiguated email.
INSTANCE_ID="${INSTANCE_ID:-$(hostname)}"
# Slugify: lowercase, replace anything not [a-z0-9-] with '-', strip leading/
# trailing hyphens. AD/email-safe while preserving readability.
INSTANCE_SLUG="$(printf '%s' "$INSTANCE_ID" | tr '[:upper:]' '[:lower:]' \
  | sed -E 's/[^a-z0-9-]+/-/g; s/^-+//; s/-+$//')"
[ -z "$INSTANCE_SLUG" ] && INSTANCE_SLUG="local"
SVC_EMAIL="${SVC_EMAIL:-governance-hub@svc.insidellm-${INSTANCE_SLUG}.local}"
SVC_NAME="${SVC_NAME:-Governance Hub (service account — ${INSTANCE_SLUG})}"
OWUI_URL="${OWUI_URL:-http://localhost:8080}"
OWUI_CONTAINER="${OWUI_CONTAINER:-insidellm-open-webui}"

# Idempotency guard
if [ -f "$ENV_FILE" ] && grep -q "^OPEN_WEBUI_API_KEY=" "$ENV_FILE"; then
  echo "[owui-svc] OPEN_WEBUI_API_KEY already present in $ENV_FILE — skipping"
  exit 0
fi

# Wait briefly for OWUI container to be ready if we were called early
for i in $(seq 1 30); do
  if docker exec "$OWUI_CONTAINER" test -f /app/backend/data/webui.db 2>/dev/null; then
    break
  fi
  sleep 2
done

echo "[owui-svc] provisioning service account $SVC_EMAIL"

# Generate a throwaway password for the auth row. We never use this —
# the service account authenticates via its API key, not via signin —
# but the auth table requires a password hash to exist.
SVC_PASSWORD="$(openssl rand -base64 32 | tr -d '/+=' | head -c 32)"

# Everything else happens inside the container: insert user + auth +
# api_key rows directly, then print the generated API key.
API_KEY=$(docker exec -i "$OWUI_CONTAINER" python3 - "$SVC_EMAIL" "$SVC_NAME" "$SVC_PASSWORD" <<'PY'
import sys, sqlite3, uuid, time, secrets, json, bcrypt

email, name, password = sys.argv[1], sys.argv[2], sys.argv[3]
db = sqlite3.connect("/app/backend/data/webui.db")

# 1) user row (admin, never-active flag via info.service_account)
row = db.execute("SELECT id FROM user WHERE email=?", (email,)).fetchone()
if row:
    user_id = row[0]
    # Ensure role=admin and mark as service account
    db.execute("UPDATE user SET role=?, info=? WHERE id=?",
               ("admin", json.dumps({"service_account": True}), user_id))
else:
    user_id = str(uuid.uuid4())
    now = int(time.time())
    db.execute(
        "INSERT INTO user (id,email,name,role,profile_image_url,created_at,updated_at,last_active_at,info) "
        "VALUES (?,?,?,?,?,?,?,?,?)",
        (user_id, email, name, "admin", "/user.png", now, now, now,
         json.dumps({"service_account": True})),
    )

# 2) auth row with bcrypt hash
pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
row = db.execute("SELECT id FROM auth WHERE email=?", (email,)).fetchone()
if row:
    db.execute("UPDATE auth SET password=?, active=1 WHERE email=?", (pw_hash, email))
else:
    db.execute("INSERT INTO auth (id,email,password,active) VALUES (?,?,?,?)",
               (user_id, email, pw_hash, 1))

# 3) api_key row (matches OWUI's own generation shape: sk- + 32 random hex)
api_key = "sk-" + secrets.token_hex(24)
key_id = str(uuid.uuid4())
now = int(time.time())
# Remove any existing keys for this user (we only want one)
db.execute("DELETE FROM api_key WHERE user_id=?", (user_id,))
db.execute(
    "INSERT INTO api_key (id,user_id,key,data,created_at,updated_at) VALUES (?,?,?,?,?,?)",
    (key_id, user_id, api_key, json.dumps({"name": "governance-hub-sync", "service_account": True}), now, now),
)

db.commit()
db.close()
print(api_key)
PY
)

if [ -z "$API_KEY" ]; then
  echo "[owui-svc] ERROR: failed to generate API key" >&2
  exit 1
fi

# Scrub any prior OPEN_WEBUI_* lines (handles re-runs after rotation and
# the case where a human bootstrapped with their personal key during
# bring-up) so the final env has exactly one source of truth.
if [ -f "$ENV_FILE" ]; then
  sed -i '/^OPEN_WEBUI_API_KEY=/d; /^OPEN_WEBUI_URL=/d; /^# Open WebUI service account/d' "$ENV_FILE"
fi

{
  echo ""
  echo "# Open WebUI service account (auto-provisioned $(date -Iseconds))"
  echo "OPEN_WEBUI_URL=http://open-webui:8080"
  echo "OPEN_WEBUI_API_KEY=$API_KEY"
} >> "$ENV_FILE"
chmod 600 "$ENV_FILE"
chown root:root "$ENV_FILE"

echo "[owui-svc] provisioned: key ends in ...${API_KEY: -8}"

# Force-recreate governance-hub so it picks up the new .env value.
# `docker restart` only restarts the process with its already-parsed
# environment — compose variable interpolation only runs on `up`.
if docker ps --format '{{.Names}}' | grep -q '^insidellm-governance-hub$'; then
  echo "[owui-svc] recreating governance-hub to pick up new API key"
  COMPOSE_DIR="$(dirname "$ENV_FILE")"
  OVERRIDE=""
  [ -f "$COMPOSE_DIR/docker-compose.override.yml" ] && OVERRIDE="-f $COMPOSE_DIR/docker-compose.override.yml"
  ( cd "$COMPOSE_DIR" && \
    docker compose -f docker-compose.yml $OVERRIDE --env-file "$ENV_FILE" \
    up -d --force-recreate governance-hub ) >/dev/null || true
fi
