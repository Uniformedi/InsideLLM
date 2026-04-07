#!/bin/bash
# =============================================================================
# Trivy CVE Scanner — runs daily via cron
# Scans all running InsideLLM container images for vulnerabilities
# =============================================================================

set -euo pipefail

LOG="/var/log/InsideLLM-trivy.log"
REPORT_DIR="/opt/InsideLLM/data/trivy-reports"
mkdir -p "$REPORT_DIR"

DATE=$(date +%Y-%m-%d)
REPORT="$REPORT_DIR/scan-$DATE.json"

log() {
  echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*" | tee -a "$LOG"
}

log "=== Starting CVE scan ==="

# Get all running container images
IMAGES=$(docker ps --format '{{.Image}}' | sort -u)

VULN_COUNT=0
CRITICAL_COUNT=0

for IMAGE in $IMAGES; do
  log "Scanning: $IMAGE"
  docker run --rm \
    -v /var/run/docker.sock:/var/run/docker.sock \
    -v "$REPORT_DIR:/reports" \
    aquasec/trivy:latest image \
    --format json \
    --output "/reports/scan-$DATE-$(echo "$IMAGE" | tr '/:' '__').json" \
    --severity HIGH,CRITICAL \
    --quiet \
    "$IMAGE" 2>>"$LOG" || log "WARNING: Scan failed for $IMAGE"

  # Count critical vulns
  SCAN_FILE="$REPORT_DIR/scan-$DATE-$(echo "$IMAGE" | tr '/:' '__').json"
  if [ -f "$SCAN_FILE" ]; then
    IMG_CRITICAL=$(cat "$SCAN_FILE" | docker run --rm -i ghcr.io/jqlang/jq:latest '[.Results[]?.Vulnerabilities[]? | select(.Severity=="CRITICAL")] | length' 2>/dev/null || echo "0")
    IMG_VULNS=$(cat "$SCAN_FILE" | docker run --rm -i ghcr.io/jqlang/jq:latest '[.Results[]?.Vulnerabilities[]?] | length' 2>/dev/null || echo "0")
    CRITICAL_COUNT=$((CRITICAL_COUNT + IMG_CRITICAL))
    VULN_COUNT=$((VULN_COUNT + IMG_VULNS))
    log "  $IMAGE: $IMG_VULNS HIGH/CRITICAL vulnerabilities ($IMG_CRITICAL critical)"
  fi
done

log "=== Scan complete: $VULN_COUNT total HIGH/CRITICAL, $CRITICAL_COUNT CRITICAL ==="

# Clean up reports older than 30 days
find "$REPORT_DIR" -name "scan-*.json" -mtime +30 -delete 2>/dev/null || true
