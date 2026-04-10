#!/usr/bin/env bash
# =============================================================================
# provision-monitoring.sh — Configure monitoring, alerting & dashboards
#
# Wires up Grafana (datasources, dashboards, alerts), Uptime Kuma (monitors,
# notifications), and LiteLLM Slack alerting on a live InsideLLM deployment.
#
# Run on the InsideLLM host (or via SSH):
#   ssh insidellm-admin@<ip> 'bash -s' < scripts/provision-monitoring.sh
#
# Prerequisites:
#   - All containers running (docker ps shows healthy)
#   - Slack webhook URL set in SLACK_WEBHOOK_URL env or auto-detected from
#     Watchtower config
#
# Idempotent: safe to run multiple times. Existing monitors are skipped.
# =============================================================================
set -euo pipefail

INSTALL_DIR="${INSIDELLM_DIR:-/opt/InsideLLM}"
UPTIME_KUMA_USER="${UPTIME_KUMA_USER:-admin}"
UPTIME_KUMA_PASS="${UPTIME_KUMA_PASS:-insidellm-admin-2024}"

# ---------------------------------------------------------------------------
# Auto-detect values from running containers
# ---------------------------------------------------------------------------
echo "=== Detecting configuration ==="

GRAFANA_PASS=$(docker inspect insidellm-grafana --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
  | grep GF_SECURITY_ADMIN_PASSWORD | cut -d= -f2)
GRAFANA_URL="http://localhost:3000"
GRAFANA_AUTH="admin:${GRAFANA_PASS}"

POSTGRES_PASS=$(docker inspect insidellm-postgres --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
  | grep POSTGRES_PASSWORD | cut -d= -f2)

# Auto-detect Slack webhook from Watchtower (shoutrrr format -> standard URL)
if [ -z "${SLACK_WEBHOOK_URL:-}" ]; then
  SHOUTRRR=$(docker inspect insidellm-watchtower --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
    | grep WATCHTOWER_NOTIFICATION_URL | cut -d= -f2 || true)
  if [[ "$SHOUTRRR" == slack://* ]]; then
    SLACK_PARTS="${SHOUTRRR#slack://}"
    SLACK_WEBHOOK_URL="https://hooks.slack.com/services/${SLACK_PARTS}"
    echo "  Slack webhook: auto-detected from Watchtower"
  else
    echo "  WARNING: No Slack webhook found. Alerts won't be sent."
    SLACK_WEBHOOK_URL=""
  fi
fi

echo "  Grafana: ${GRAFANA_URL}"
echo "  PostgreSQL password: ${POSTGRES_PASS:+detected}"
echo "  Slack webhook: ${SLACK_WEBHOOK_URL:+configured}"
echo ""

# ---------------------------------------------------------------------------
# 1. Fix Grafana provisioning directory structure
# ---------------------------------------------------------------------------
echo "=== Step 1: Grafana provisioning structure ==="

PROV_DIR="${INSTALL_DIR}/grafana/provisioning"
if [ -f "${PROV_DIR}/datasources.yml" ] && [ ! -d "${PROV_DIR}/datasources" ]; then
  sudo mkdir -p "${PROV_DIR}/datasources" "${PROV_DIR}/dashboards"
  sudo mv "${PROV_DIR}/datasources.yml" "${PROV_DIR}/datasources/datasources.yml"
  echo "  Moved datasources.yml into datasources/"
fi
if [ -f "${PROV_DIR}/dashboards.yml" ] && [ ! -d "${PROV_DIR}/dashboards" ]; then
  sudo mkdir -p "${PROV_DIR}/dashboards"
  sudo mv "${PROV_DIR}/dashboards.yml" "${PROV_DIR}/dashboards/dashboards.yml"
  echo "  Moved dashboards.yml into dashboards/"
fi

# Ensure subdirectories exist
sudo mkdir -p "${PROV_DIR}/datasources" "${PROV_DIR}/dashboards"

# Write datasources config (overwrites with current password)
sudo tee "${PROV_DIR}/datasources/datasources.yml" > /dev/null <<DSEOF
apiVersion: 1

datasources:
  - name: Loki
    type: loki
    access: proxy
    url: http://loki:3100
    isDefault: true
    editable: false

  - name: PostgreSQL
    type: postgres
    url: postgres:5432
    database: litellm
    user: litellm
    secureJsonData:
      password: ${POSTGRES_PASS}
    jsonData:
      sslmode: disable
      maxOpenConns: 5
      maxIdleConns: 2
      connMaxLifetime: 14400
    editable: false
DSEOF

# Write dashboards provisioning config
sudo tee "${PROV_DIR}/dashboards/dashboards.yml" > /dev/null <<DBEOF
apiVersion: 1

providers:
  - name: InsideLLM
    orgId: 1
    folder: InsideLLM
    type: file
    disableDeletion: false
    updateIntervalSeconds: 30
    options:
      path: /var/lib/grafana/dashboards
      foldersFromFilesStructure: false
DBEOF

echo "  Provisioning files written"

# Restart Grafana
echo "  Restarting Grafana..."
docker restart insidellm-grafana > /dev/null
sleep 5
for i in $(seq 1 12); do
  STATUS=$(curl -s -o /dev/null -w "%{http_code}" "${GRAFANA_URL}/api/health" 2>/dev/null)
  if [ "$STATUS" = "200" ]; then echo "  Grafana healthy"; break; fi
  sleep 3
done

# Verify datasources loaded
DS_COUNT=$(curl -s -u "${GRAFANA_AUTH}" "${GRAFANA_URL}/api/datasources" | python3 -c "import json,sys; print(len(json.load(sys.stdin)))" 2>/dev/null)
echo "  Datasources loaded: ${DS_COUNT}"

# ---------------------------------------------------------------------------
# 2. Grafana: Slack contact point & notification policy
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 2: Grafana alerting ==="

if [ -n "${SLACK_WEBHOOK_URL}" ]; then
  # Check if contact point already exists
  EXISTING_CP=$(curl -s -u "${GRAFANA_AUTH}" "${GRAFANA_URL}/api/v1/provisioning/contact-points" \
    | python3 -c "import json,sys; cps=json.load(sys.stdin); print('yes' if any(c['name']=='InsideLLM Slack' for c in cps) else 'no')" 2>/dev/null)

  if [ "$EXISTING_CP" = "no" ]; then
    curl -s -X POST "${GRAFANA_URL}/api/v1/provisioning/contact-points" \
      -u "${GRAFANA_AUTH}" \
      -H "Content-Type: application/json" \
      -H "X-Disable-Provenance: true" \
      -d "{\"name\":\"InsideLLM Slack\",\"type\":\"slack\",\"settings\":{\"url\":\"${SLACK_WEBHOOK_URL}\"}}" > /dev/null
    echo "  Created Slack contact point"
  else
    echo "  Slack contact point already exists"
  fi

  # Set default notification policy
  curl -s -X PUT "${GRAFANA_URL}/api/v1/provisioning/policies" \
    -u "${GRAFANA_AUTH}" \
    -H "Content-Type: application/json" \
    -H "X-Disable-Provenance: true" \
    -d '{"receiver":"InsideLLM Slack","group_by":["grafana_folder","alertname"],"group_wait":"30s","group_interval":"5m","repeat_interval":"4h"}' > /dev/null
  echo "  Notification policy set to InsideLLM Slack"
fi

# ---------------------------------------------------------------------------
# 3. Grafana: Alert rules
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 3: Grafana alert rules ==="

# Get datasource UIDs
LOKI_UID=$(curl -s -u "${GRAFANA_AUTH}" "${GRAFANA_URL}/api/datasources" \
  | python3 -c "import json,sys; ds=json.load(sys.stdin); print(next((d['uid'] for d in ds if d['name']=='Loki'), 'none'))" 2>/dev/null)
PG_UID=$(curl -s -u "${GRAFANA_AUTH}" "${GRAFANA_URL}/api/datasources" \
  | python3 -c "import json,sys; ds=json.load(sys.stdin); print(next((d['uid'] for d in ds if d['name']=='PostgreSQL'), 'none'))" 2>/dev/null)

# Get or create the InsideLLM folder
FOLDER_UID=$(curl -s -u "${GRAFANA_AUTH}" "${GRAFANA_URL}/api/search?type=dash-folder" \
  | python3 -c "import json,sys; f=json.load(sys.stdin); print(next((x['uid'] for x in f if x['title']=='InsideLLM'), 'general'))" 2>/dev/null)

# Check existing rules to avoid duplicates
EXISTING_RULES=$(curl -s -u "${GRAFANA_AUTH}" "${GRAFANA_URL}/api/v1/provisioning/alert-rules" \
  | python3 -c "import json,sys; rules=json.load(sys.stdin); print(','.join(r['title'] for r in rules))" 2>/dev/null)

create_alert() {
  local TITLE="$1"
  local BODY="$2"
  if echo "${EXISTING_RULES}" | grep -qF "${TITLE}"; then
    echo "  [skip] ${TITLE} (already exists)"
    return
  fi
  RESULT=$(curl -s -X POST "${GRAFANA_URL}/api/v1/provisioning/alert-rules" \
    -u "${GRAFANA_AUTH}" \
    -H "Content-Type: application/json" \
    -H "X-Disable-Provenance: true" \
    -d "${BODY}")
  UID=$(echo "$RESULT" | python3 -c "import json,sys; print(json.load(sys.stdin).get('uid','FAILED'))" 2>/dev/null)
  echo "  [created] ${TITLE} (${UID})"
}

# Alert 1: High Error Rate
create_alert "High Error Rate" "{
  \"title\":\"High Error Rate\",\"ruleGroup\":\"InsideLLM Alerts\",\"folderUID\":\"${FOLDER_UID}\",
  \"condition\":\"C\",\"for\":\"5m\",\"noDataState\":\"OK\",\"execErrState\":\"OK\",
  \"data\":[
    {\"refId\":\"A\",\"datasourceUid\":\"${LOKI_UID}\",\"relativeTimeRange\":{\"from\":300,\"to\":0},
     \"model\":{\"expr\":\"count_over_time({service=~\\\"litellm|open-webui\\\"} |~ \\\"error|Error|ERROR|500|502|503\\\" [5m])\",\"refId\":\"A\"}},
    {\"refId\":\"B\",\"datasourceUid\":\"-100\",\"relativeTimeRange\":{\"from\":0,\"to\":0},
     \"model\":{\"type\":\"reduce\",\"expression\":\"A\",\"reducer\":\"sum\",\"refId\":\"B\"}},
    {\"refId\":\"C\",\"datasourceUid\":\"-100\",\"relativeTimeRange\":{\"from\":0,\"to\":0},
     \"model\":{\"type\":\"threshold\",\"expression\":\"B\",\"conditions\":[{\"evaluator\":{\"type\":\"gt\",\"params\":[50]}}],\"refId\":\"C\"}}
  ],
  \"labels\":{\"severity\":\"warning\",\"team\":\"insidellm\"},
  \"annotations\":{\"summary\":\"High error rate detected in InsideLLM services\",\"description\":\"More than 50 error log entries in the last 5 minutes.\"}
}"

# Alert 2: Budget Threshold
create_alert "Budget Threshold Exceeded" "{
  \"title\":\"Budget Threshold Exceeded\",\"ruleGroup\":\"InsideLLM Alerts\",\"folderUID\":\"${FOLDER_UID}\",
  \"condition\":\"C\",\"for\":\"0s\",\"noDataState\":\"OK\",\"execErrState\":\"OK\",
  \"data\":[
    {\"refId\":\"A\",\"datasourceUid\":\"${PG_UID}\",\"relativeTimeRange\":{\"from\":2592000,\"to\":0},
     \"model\":{\"rawSql\":\"SELECT NOW() AS time, COALESCE(SUM(spend), 0) AS total_spend FROM \\\"LiteLLM_SpendLogs\\\" WHERE \\\"startTime\\\" > date_trunc('month', NOW())\",\"format\":\"table\",\"refId\":\"A\"}},
    {\"refId\":\"B\",\"datasourceUid\":\"-100\",\"relativeTimeRange\":{\"from\":0,\"to\":0},
     \"model\":{\"type\":\"reduce\",\"expression\":\"A\",\"reducer\":\"last\",\"refId\":\"B\"}},
    {\"refId\":\"C\",\"datasourceUid\":\"-100\",\"relativeTimeRange\":{\"from\":0,\"to\":0},
     \"model\":{\"type\":\"threshold\",\"expression\":\"B\",\"conditions\":[{\"evaluator\":{\"type\":\"gt\",\"params\":[80]}}],\"refId\":\"C\"}}
  ],
  \"labels\":{\"severity\":\"critical\",\"team\":\"insidellm\"},
  \"annotations\":{\"summary\":\"Monthly API spend exceeds 80% of budget\",\"description\":\"Total monthly spend has exceeded 80 USD of the 100 USD global budget.\"}
}"

# Alert 3: DLP Block Spike
create_alert "DLP Block Spike" "{
  \"title\":\"DLP Block Spike\",\"ruleGroup\":\"InsideLLM Alerts\",\"folderUID\":\"${FOLDER_UID}\",
  \"condition\":\"C\",\"for\":\"5m\",\"noDataState\":\"OK\",\"execErrState\":\"OK\",
  \"data\":[
    {\"refId\":\"A\",\"datasourceUid\":\"${LOKI_UID}\",\"relativeTimeRange\":{\"from\":3600,\"to\":0},
     \"model\":{\"expr\":\"count_over_time({service=\\\"open-webui\\\"} |= \\\"DLP\\\" |= \\\"blocked\\\" [1h])\",\"refId\":\"A\"}},
    {\"refId\":\"B\",\"datasourceUid\":\"-100\",\"relativeTimeRange\":{\"from\":0,\"to\":0},
     \"model\":{\"type\":\"reduce\",\"expression\":\"A\",\"reducer\":\"sum\",\"refId\":\"B\"}},
    {\"refId\":\"C\",\"datasourceUid\":\"-100\",\"relativeTimeRange\":{\"from\":0,\"to\":0},
     \"model\":{\"type\":\"threshold\",\"expression\":\"B\",\"conditions\":[{\"evaluator\":{\"type\":\"gt\",\"params\":[10]}}],\"refId\":\"C\"}}
  ],
  \"labels\":{\"severity\":\"warning\",\"team\":\"insidellm\"},
  \"annotations\":{\"summary\":\"DLP blocking spike detected\",\"description\":\"More than 10 DLP blocks in the last hour.\"}
}"

# Alert 4: Service Restart Loop
create_alert "Service Restart Loop" "{
  \"title\":\"Service Restart Loop\",\"ruleGroup\":\"InsideLLM Alerts\",\"folderUID\":\"${FOLDER_UID}\",
  \"condition\":\"C\",\"for\":\"5m\",\"noDataState\":\"OK\",\"execErrState\":\"OK\",
  \"data\":[
    {\"refId\":\"A\",\"datasourceUid\":\"${LOKI_UID}\",\"relativeTimeRange\":{\"from\":900,\"to\":0},
     \"model\":{\"expr\":\"count_over_time({service=~\\\".+\\\"} |~ \\\"restarting|OOMKilled|exited with code\\\" [15m])\",\"refId\":\"A\"}},
    {\"refId\":\"B\",\"datasourceUid\":\"-100\",\"relativeTimeRange\":{\"from\":0,\"to\":0},
     \"model\":{\"type\":\"reduce\",\"expression\":\"A\",\"reducer\":\"sum\",\"refId\":\"B\"}},
    {\"refId\":\"C\",\"datasourceUid\":\"-100\",\"relativeTimeRange\":{\"from\":0,\"to\":0},
     \"model\":{\"type\":\"threshold\",\"expression\":\"B\",\"conditions\":[{\"evaluator\":{\"type\":\"gt\",\"params\":[3]}}],\"refId\":\"C\"}}
  ],
  \"labels\":{\"severity\":\"critical\",\"team\":\"insidellm\"},
  \"annotations\":{\"summary\":\"Service restart loop detected\",\"description\":\"Multiple container restarts or OOM kills in the last 15 minutes.\"}
}"

# ---------------------------------------------------------------------------
# 4. LiteLLM: Slack webhook for budget alerting
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 4: LiteLLM Slack alerting ==="

if [ -n "${SLACK_WEBHOOK_URL}" ]; then
  COMPOSE_FILE="${INSTALL_DIR}/docker-compose.yml"
  if sudo grep -q "SLACK_WEBHOOK_URL" "${COMPOSE_FILE}" 2>/dev/null; then
    echo "  SLACK_WEBHOOK_URL already in docker-compose.yml"
  else
    sudo sed -i "/LITELLM_LOG.*INFO/a\\      SLACK_WEBHOOK_URL: \"${SLACK_WEBHOOK_URL}\"" "${COMPOSE_FILE}"
    echo "  Added SLACK_WEBHOOK_URL to docker-compose.yml"
    echo "  Restarting LiteLLM..."
    cd "${INSTALL_DIR}" && sudo docker compose up -d litellm > /dev/null 2>&1
    # Wait for healthy
    for i in $(seq 1 24); do
      STATUS=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:4000/health/liveliness 2>/dev/null)
      if [ "$STATUS" = "200" ]; then echo "  LiteLLM healthy"; break; fi
      sleep 5
    done
  fi
else
  echo "  Skipped (no Slack webhook)"
fi

# ---------------------------------------------------------------------------
# 5. Uptime Kuma: Admin setup + service monitors
# ---------------------------------------------------------------------------
echo ""
echo "=== Step 5: Uptime Kuma monitors ==="

# Create a Node.js provisioning script and run it inside the container
cat > /tmp/provision-uptime-kuma.js << 'UKEOF'
const { io } = require("socket.io-client");
const socket = io("http://localhost:3001", { reconnection: false, timeout: 10000 });

const ADMIN_USER = process.env.UK_USER || "admin";
const ADMIN_PASS = process.env.UK_PASS || "insidellm-admin-2024";
const SLACK_WEBHOOK = process.env.SLACK_WEBHOOK || "";

const MONITORS = [
  { name: "Open WebUI", type: "http", url: "http://open-webui:8080/health", interval: 60 },
  { name: "LiteLLM API", type: "http", url: "http://litellm:4000/health/liveliness", interval: 60 },
  { name: "Nginx HTTPS", type: "http", url: "https://localhost/nginx-health", interval: 60, ignoreTls: true },
  { name: "Netdata", type: "http", url: "http://netdata:19999/api/v1/info", interval: 120 },
  { name: "Grafana", type: "http", url: "http://grafana:3000/api/health", interval: 120 },
  { name: "PostgreSQL", type: "port", hostname: "postgres", port: 5432, interval: 60 },
  { name: "Redis", type: "port", hostname: "redis", port: 6379, interval: 60 },
  { name: "Loki", type: "http", url: "http://loki:3100/ready", interval: 120 },
  { name: "DocForge", type: "http", url: "http://docforge:3000/health", interval: 120 },
  { name: "Governance Hub", type: "http", url: "http://governance-hub:8090/health", interval: 120 },
];

const monitorData = {};
const notificationData = [];
socket.on("monitorList", (data) => { Object.assign(monitorData, data); });
socket.on("notificationList", (data) => { notificationData.length = 0; notificationData.push(...data); });

socket.on("connect", () => {
  socket.emit("needSetup", (needSetup) => {
    if (needSetup) {
      socket.emit("setup", ADMIN_USER, ADMIN_PASS, (res) => {
        if (!res.ok) { console.error("Setup failed:", res.msg); process.exit(1); }
        console.log("  Admin account created");
        proceed();
      });
    } else {
      socket.emit("login", { username: ADMIN_USER, password: ADMIN_PASS, token: "" }, (res) => {
        if (!res.ok) { console.error("Login failed:", res.msg); process.exit(1); }
        proceed();
      });
    }
  });
});

function proceed() {
  // Wait for monitorList event
  setTimeout(() => {
    const existingNames = new Set(Object.values(monitorData).map(m => m.name));
    const toAdd = MONITORS.filter(m => !existingNames.has(m.name));

    if (toAdd.length === 0) {
      console.log("  All monitors already exist (" + existingNames.size + " total)");
      setupNotification();
      return;
    }

    let done = 0;
    toAdd.forEach(m => {
      const monitor = {
        name: m.name, type: m.type, url: m.url || null,
        hostname: m.hostname || null, port: m.port || null,
        interval: m.interval, maxretries: 3, retryInterval: 30,
        ignoreTls: m.ignoreTls || false, accepted_statuscodes: ["200-299"],
        active: true, notificationIDList: {},
      };
      socket.emit("add", monitor, (res) => {
        done++;
        if (res.ok) console.log("  + " + m.name);
        else console.log("  ! " + m.name + ": " + (res.msg || "failed"));
        if (done === toAdd.length) setupNotification();
      });
    });
  }, 2000);
}

function setupNotification() {
  if (!SLACK_WEBHOOK) { finish(); return; }

  // Use the notificationList event data (populated on login)
  setTimeout(() => {
    const existing = notificationData.find(n => n.name === "InsideLLM Slack");
    if (existing) {
      console.log("  Slack notification already configured");
      applyNotification(existing.id);
      return;
    }

    const notification = {
      name: "InsideLLM Slack", type: "slack", isDefault: true, active: true,
      slackwebhookURL: SLACK_WEBHOOK, slackchannelnotify: true,
      slackusername: "InsideLLM Uptime Kuma", slackiconemo: ":robot_face:",
    };
    socket.emit("addNotification", notification, null, (res) => {
      if (res.ok) {
        console.log("  Slack notification created");
        applyNotification(res.id);
      } else {
        console.log("  Notification failed:", res.msg);
        finish();
      }
    });
  }, 500);
}

function applyNotification(notifId) {
  // Wait for updated monitorList
  setTimeout(() => {
    const ids = Object.keys(monitorData);
    if (ids.length === 0) { finish(); return; }

    // Check if all monitors already have this notification
    const needsUpdate = ids.filter(id => {
      const n = monitorData[id].notificationIDList || {};
      return !n[notifId] && !n[String(notifId)];
    });

    if (needsUpdate.length === 0) {
      console.log("  Slack already applied to all monitors");
      finish();
      return;
    }

    let done = 0;
    needsUpdate.forEach(id => {
      const m = monitorData[id];
      m.notificationIDList = m.notificationIDList || {};
      m.notificationIDList[notifId] = true;
      socket.emit("editMonitor", m, () => {
        done++;
        if (done === needsUpdate.length) {
          console.log("  Slack applied to " + needsUpdate.length + " monitors");
          finish();
        }
      });
    });
  }, 1000);
}

function finish() { socket.disconnect(); process.exit(0); }

socket.on("connect_error", (e) => { console.error("Connection error:", e.message); process.exit(1); });
setTimeout(() => { console.error("  Timeout"); process.exit(1); }, 30000);
UKEOF

# Copy script into container's /app dir (so node_modules resolve) and run
docker cp /tmp/provision-uptime-kuma.js insidellm-uptime-kuma:/app/provision-uptime-kuma.js
docker exec \
  -e "UK_USER=${UPTIME_KUMA_USER}" \
  -e "UK_PASS=${UPTIME_KUMA_PASS}" \
  -e "SLACK_WEBHOOK=${SLACK_WEBHOOK_URL}" \
  insidellm-uptime-kuma node /app/provision-uptime-kuma.js
docker exec insidellm-uptime-kuma rm -f /app/provision-uptime-kuma.js
rm -f /tmp/provision-uptime-kuma.js

# ---------------------------------------------------------------------------
# 6. Verification
# ---------------------------------------------------------------------------
echo ""
echo "=== Verification ==="

echo "Grafana datasources:"
curl -s -u "${GRAFANA_AUTH}" "${GRAFANA_URL}/api/datasources" \
  | python3 -c "import json,sys; [print(f'  - {d[\"name\"]}: {d[\"type\"]}') for d in json.load(sys.stdin)]" 2>/dev/null

echo "Grafana dashboards:"
curl -s -u "${GRAFANA_AUTH}" "${GRAFANA_URL}/api/search?type=dash-db" \
  | python3 -c "import json,sys; [print(f'  - {d[\"title\"]}') for d in json.load(sys.stdin)]" 2>/dev/null

echo "Grafana alert rules:"
curl -s -u "${GRAFANA_AUTH}" "${GRAFANA_URL}/api/v1/provisioning/alert-rules" \
  | python3 -c "import json,sys; [print(f'  - [{r.get(\"labels\",{}).get(\"severity\",\"?\")}] {r[\"title\"]}') for r in json.load(sys.stdin)]" 2>/dev/null

echo "Grafana contact points:"
curl -s -u "${GRAFANA_AUTH}" "${GRAFANA_URL}/api/v1/provisioning/contact-points" \
  | python3 -c "import json,sys; [print(f'  - {c[\"name\"]}: {c[\"type\"]}') for c in json.load(sys.stdin)]" 2>/dev/null

echo "LiteLLM Slack:"
docker inspect insidellm-litellm --format '{{range .Config.Env}}{{println .}}{{end}}' 2>/dev/null \
  | grep -q SLACK_WEBHOOK && echo "  - Configured" || echo "  - Not configured"

echo ""
echo "=== Provisioning complete ==="
echo "  Grafana:     https://<host>/grafana/"
echo "  Uptime Kuma: https://<host>/status/"
echo "  Credentials:"
echo "    Grafana:     admin / (auto-generated)"
echo "    Uptime Kuma: ${UPTIME_KUMA_USER} / ${UPTIME_KUMA_PASS}"
