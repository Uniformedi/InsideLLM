#!/usr/bin/env bash
# ============================================================================
# smoke-demo-path.sh — fast smoke test for the Friday demo's critical path.
#
# Runs TestPlan_V1.md §4a/§4b/§4c/§4f/§4h in parallel plus three additional
# Collections-pack checks. ~20s end-to-end on a warm VM, vs. ~4–5 min for
# the full TestPlan.
#
# Exit code 0 if every critical-path check passes, non-zero if any fails.
# Each check prints "OK" or "FAIL: <reason>" on its own line.
#
# Env:
#   HOST  — VM host (default 192.168.100.10)
#   KEY   — LiteLLM master key; auto-read from /opt/InsideLLM/.env if unset
# ============================================================================

set -u
HOST="${HOST:-192.168.100.10}"
ENV_FILE="${ENV_FILE:-/opt/InsideLLM/.env}"

if [[ -z "${KEY:-}" ]]; then
    if [[ -r "$ENV_FILE" ]]; then
        KEY="$(grep -E '^LITELLM_MASTER_KEY=' "$ENV_FILE" | cut -d= -f2- | tr -d '"')"
    fi
fi
if [[ -z "${KEY:-}" ]]; then
    echo "KEY not set and $ENV_FILE not readable. Set KEY env var." >&2
    exit 2
fi

CURL="curl -sk --max-time 8 -u insidellm-admin:$KEY"

# Results dir — one file per check so we can harvest after wait.
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

check() {
    local name="$1"; shift
    local result
    if result="$("$@" 2>&1)"; then
        echo "OK   $name" > "$TMP/$name"
    else
        echo "FAIL $name: $result" > "$TMP/$name"
    fi
}

# -- 4a: every container healthy --------------------------------------------
check_containers() {
    local unhealthy
    unhealthy="$(docker ps --format '{{.Names}}\t{{.Status}}' 2>&1 | grep -v healthy | grep -v '^$' || true)"
    if [[ -z "$unhealthy" ]]; then
        echo "all healthy"
    else
        echo "unhealthy: $unhealthy"
        return 1
    fi
}

# -- 4b: Gov-Hub alive, new tables present -----------------------------------
check_govhub_alive() {
    $CURL "https://$HOST/governance/health" | grep -q '"ok"' && echo "ok"
}
check_govhub_tables() {
    local out
    out="$(docker exec insidellm-postgres psql -U litellm -d litellm -tAc \
        "SELECT string_agg(tablename, ',') FROM pg_tables WHERE tablename LIKE 'governance_%'" 2>&1)"
    for t in governance_agents governance_actions governance_audit_chain governance_instances; do
        if ! echo "$out" | grep -q "$t"; then
            echo "missing $t"; return 1
        fi
    done
    echo "tables present"
}

# -- 4c: Core action catalog seeded ------------------------------------------
check_catalog() {
    local total
    total="$($CURL "https://$HOST/governance/api/v1/actions/?tenant_id=core" | \
        python3 -c 'import sys,json; print(json.load(sys.stdin).get("total",0))' 2>&1)"
    if [[ "$total" =~ ^[0-9]+$ ]] && (( total >= 20 )); then
        echo "$total actions"
    else
        echo "expected >=20 core actions, got: $total"; return 1
    fi
}

# -- 4d: Portfolio dashboard renders -----------------------------------------
check_portfolio() {
    $CURL "https://$HOST/governance/api/v1/portfolio/overview" | grep -q '"instances"' \
        && echo "portfolio ok"
}

# -- Collections: Dispute Handler present, status=published ------------------
check_dispute_handler() {
    local status
    status="$($CURL "https://$HOST/governance/api/v1/agents/example-tenant/dispute-handler" | \
        python3 -c 'import sys,json; j=json.load(sys.stdin); print(j.get("status","?"))' 2>&1)"
    if [[ "$status" == "published" ]]; then
        echo "published"
    else
        echo "status='$status' (expected published)"; return 1
    fi
}

# -- Collections: ledger table seeded ----------------------------------------
check_ledger() {
    local n
    n="$(docker exec insidellm-postgres psql -U litellm -d litellm -tAc \
        "SELECT COUNT(*) FROM demo_collections_ledger" 2>&1 | tr -d ' ')"
    if [[ "$n" =~ ^[0-9]+$ ]] && (( n >= 3 )); then
        echo "$n ledger rows"
    else
        echo "expected >=3 ledger rows, got: $n"; return 1
    fi
}

# -- 4h: DLP scan redacts PII ------------------------------------------------
check_dlp() {
    local hits
    hits="$($CURL -X POST "https://$HOST/governance/api/v1/notifications/scan" \
        -H 'Content-Type: application/json' \
        -d '{"text":"Customer SSN 123-45-6789 disputed account 12345678"}' | \
        python3 -c 'import sys,json; print(json.load(sys.stdin).get("hit_count",0))' 2>&1)"
    if [[ "$hits" =~ ^[0-9]+$ ]] && (( hits >= 2 )); then
        echo "$hits DLP hits"
    else
        echo "expected >=2 DLP hits, got: $hits"; return 1
    fi
}

# -- Collections: audit chain is valid + has >=50 entries --------------------
check_audit_chain() {
    local stats valid count
    stats="$($CURL "https://$HOST/governance/api/v1/audit/chain/stats")"
    count="$(echo "$stats" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("total_entries",0))' 2>&1)"
    if [[ ! "$count" =~ ^[0-9]+$ ]] || (( count < 50 )); then
        echo "chain has only $count entries (expected >=50)"; return 1
    fi
    valid="$($CURL -X POST "https://$HOST/governance/api/v1/audit/chain/verify" | \
        python3 -c 'import sys,json; print(json.load(sys.stdin).get("valid",False))' 2>&1)"
    if [[ "$valid" == "True" ]]; then
        echo "chain valid, $count entries"
    else
        echo "chain verify returned valid=$valid"; return 1
    fi
}

# -- Launch all checks in parallel -------------------------------------------
echo "Running demo-path smoke in parallel against https://$HOST/ ..."
echo

check "4a-containers"       check_containers        &
check "4b-govhub-alive"     check_govhub_alive      &
check "4b-govhub-tables"    check_govhub_tables     &
check "4c-catalog"          check_catalog           &
check "4d-portfolio"        check_portfolio         &
check "cx-dispute-handler"  check_dispute_handler   &
check "cx-ledger"           check_ledger            &
check "4h-dlp"              check_dlp               &
check "cx-audit-chain"      check_audit_chain       &
wait

# -- Harvest + summarize -----------------------------------------------------
fails=0
for f in "$TMP"/*; do
    line="$(cat "$f")"
    echo "  $line"
    [[ "$line" =~ ^FAIL ]] && fails=$((fails + 1))
done

echo
if (( fails == 0 )); then
    echo "All $(ls "$TMP" | wc -l) critical-path checks green. Demo path is intact."
    exit 0
else
    echo "$fails check(s) failed. Demo path is NOT ready."
    exit 1
fi
