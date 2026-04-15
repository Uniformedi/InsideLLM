#!/usr/bin/env bash
# ad-join-runner.sh — host-side realm-join executor.
#
# Triggered by a systemd path unit when /opt/InsideLLM/ad-join-request.json
# appears (Governance Hub writes it). Reads the request, runs `realm join`
# (or `realm leave`), writes /opt/InsideLLM/ad-join-status.json with the
# outcome, and deletes the request so the password isn't persisted.
#
# Request shape:
#   { "action": "join" | "leave",
#     "user":   "Domain Admin sAMAccountName",   # required for join
#     "password": "domain admin password",        # required for join
#     "ou":     "OU=Servers,DC=uniformedi,DC=local"  # optional
#   }
#
# Status shape (always written, even on failure):
#   { "ok": true|false,
#     "action": "join" | "leave",
#     "started_at": "...",
#     "completed_at": "...",
#     "exit_code": 0,
#     "stdout": "...",
#     "stderr": "...",
#     "joined": true|false,            # post-state, from `realm list`
#     "domain": "uniformedi.local"      # post-state
#   }

set -uo pipefail

REQUEST="/opt/InsideLLM/ad-join-request.json"
STATUS="/opt/InsideLLM/ad-join-status.json"
LOG="/var/log/InsideLLM-ad-join.log"

log() { echo "[$(date -Iseconds)] $*" | tee -a "$LOG" ; }

# Always remove the request when we're done, regardless of outcome.
trap 'rm -f "$REQUEST"' EXIT

[ -f "$REQUEST" ] || { log "no request file, exiting"; exit 0; }

ACTION="$(jq -r '.action // ""' "$REQUEST")"
USER="$(jq -r '.user // ""' "$REQUEST")"
PASSWORD="$(jq -r '.password // ""' "$REQUEST")"
OU="$(jq -r '.ou // ""' "$REQUEST")"
DOMAIN="$(jq -r '.domain // ""' "$REQUEST")"

if [ -z "$DOMAIN" ]; then
  # Default to whatever's in /etc/krb5.conf (set by cloud-init from vm_domain).
  DOMAIN="$(awk -F= '/default_realm/ {gsub(/[ \t]/, "", $2); print tolower($2); exit}' /etc/krb5.conf 2>/dev/null)"
fi

STARTED="$(date -Iseconds)"
log "starting action=$ACTION domain=$DOMAIN user=$USER"

write_status() {
  local ok="$1" exit_code="$2" stdout="$3" stderr="$4"
  local joined="false" current_domain=""
  if realm list >/dev/null 2>&1 && realm list | grep -q "domain-name:"; then
    joined="true"
    current_domain="$(realm list | awk '/domain-name:/ {print $2; exit}')"
  fi
  jq -n \
    --arg ok "$ok" \
    --arg action "$ACTION" \
    --arg started "$STARTED" \
    --arg completed "$(date -Iseconds)" \
    --argjson exit_code "$exit_code" \
    --arg stdout "$stdout" \
    --arg stderr "$stderr" \
    --arg joined "$joined" \
    --arg domain "$current_domain" \
    '{ok: ($ok == "true"), action: $action, started_at: $started,
      completed_at: $completed, exit_code: $exit_code, stdout: $stdout,
      stderr: $stderr, joined: ($joined == "true"), domain: $domain}' \
    > "$STATUS"
  chmod 0644 "$STATUS"
}

case "$ACTION" in
  join)
    if [ -z "$USER" ] || [ -z "$PASSWORD" ] || [ -z "$DOMAIN" ]; then
      write_status false 1 "" "missing user/password/domain in request"
      exit 1
    fi
    OU_FLAG=()
    [ -n "$OU" ] && OU_FLAG=(--computer-ou="$OU")
    out=$(printf '%s' "$PASSWORD" | realm join \
            --user="$USER" \
            "${OU_FLAG[@]}" \
            --install=/ \
            "$DOMAIN" 2>&1)
    code=$?
    log "realm join exit=$code"
    if [ $code -eq 0 ]; then
      # Post-join wiring for Cockpit / SSH SSSD-backed logins:
      #   - sss PAM stack gets enabled (usually auto-added by realm join, but
      #     --enable is idempotent and guarantees it when a prior leave has
      #     left a stale state)
      #   - mkhomedir creates /home/<user>@<domain> on first login
      #   - sssd is restarted so enumeration, group caching, and pam_sss
      #     reflect the freshly-written sssd.conf
      # Best-effort: non-fatal if any step errors; realm join is already done.
      pam-auth-update --enable sss --enable mkhomedir 2>/dev/null || true
      systemctl restart sssd 2>/dev/null || true

      # Smoke test: confirm SSSD can resolve the account we joined with.
      # Log the result into stdout so it surfaces in the Hub status card.
      resolve_check=$(getent passwd "$USER@$DOMAIN" 2>&1 || echo "(not resolved)")
      out="${out}

[ad-join-runner] post-join smoke test:
  getent passwd $USER@$DOMAIN -> ${resolve_check}"

      write_status true 0 "$out" ""
    else
      write_status false "$code" "" "$out"
    fi
    ;;
  leave)
    out=$(realm leave 2>&1)
    code=$?
    log "realm leave exit=$code"
    write_status $([ $code -eq 0 ] && echo true || echo false) "$code" "$out" ""
    ;;
  *)
    write_status false 1 "" "unknown action: $ACTION"
    exit 1
    ;;
esac
