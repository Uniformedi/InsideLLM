#!/usr/bin/env bash
# ============================================================================
# demo-day-bootstrap.sh — prepare the demo VM for a live walkthrough.
#
# What it does, in order:
#   1. Seed Dispute Handler + Collections ledger (idempotent).
#   2. Verify the critical demo path via smoke-demo-path.sh.
#   3. Take a pre-rehearsal Hyper-V snapshot (via SSH to the Hyper-V host).
#   4. Optionally set the demo VM clock to 22:15 for the §1692c out-of-hours
#      demo (skip with NO_CLOCK=1).
#
# Run this ONCE after a clean deploy, then use Hyper-V checkpoint restore
# to return to this state between rehearsals.
#
# Env:
#   HOST          — demo VM host (default 192.168.100.10)
#   VM_NAME       — Hyper-V VM name (default InsideLLM)
#   HYPERV_HOST   — Hyper-V host to SSH for snapshot (default skip snapshot)
#   HYPERV_USER   — Hyper-V host user (default Administrator)
#   SNAPSHOT_NAME — snapshot label (default seeded-clean-$(date +%s))
#   NO_CLOCK      — set to 1 to skip the clock reset
#   NO_SEED       — set to 1 to skip the seed step (use if already seeded)
#   NO_SNAPSHOT   — set to 1 to skip the snapshot step
#
# Exit 0 on success; non-zero if any prerequisite fails.
# ============================================================================

set -eu
HOST="${HOST:-192.168.100.10}"
VM_NAME="${VM_NAME:-InsideLLM}"
SNAPSHOT_NAME="${SNAPSHOT_NAME:-seeded-clean-$(date +%s)}"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

say() { printf '==> %s\n' "$*"; }
warn() { printf 'WARN: %s\n' "$*" >&2; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

# -- Step 1: Seed ------------------------------------------------------------

if [[ "${NO_SEED:-0}" != "1" ]]; then
    say "Seeding Dispute Handler + Collections ledger"
    if [[ -x "$SCRIPT_DIR/seed-dispute-handler.py" ]]; then
        python3 "$SCRIPT_DIR/seed-dispute-handler.py" \
            || die "seed-dispute-handler.py failed; aborting"
    else
        die "seed-dispute-handler.py not found or not executable at $SCRIPT_DIR"
    fi
    echo
fi

# -- Step 2: Smoke-test ------------------------------------------------------

say "Running demo-path smoke test"
if [[ -x "$SCRIPT_DIR/smoke-demo-path.sh" ]]; then
    HOST="$HOST" "$SCRIPT_DIR/smoke-demo-path.sh" \
        || die "Smoke test failed — do NOT snapshot this state. Fix first."
else
    warn "smoke-demo-path.sh not found; skipping (NOT RECOMMENDED)"
fi
echo

# -- Step 3: Hyper-V snapshot -----------------------------------------------

if [[ "${NO_SNAPSHOT:-0}" != "1" ]]; then
    if [[ -z "${HYPERV_HOST:-}" ]]; then
        warn "HYPERV_HOST not set; skipping snapshot step."
        warn "Take a snapshot manually from the Hyper-V host:"
        warn "  Checkpoint-VM -Name $VM_NAME -SnapshotName '$SNAPSHOT_NAME'"
    else
        say "Taking Hyper-V snapshot: $SNAPSHOT_NAME"
        HYPERV_USER="${HYPERV_USER:-Administrator}"
        ssh "${HYPERV_USER}@${HYPERV_HOST}" \
            "powershell -Command \"Checkpoint-VM -Name '$VM_NAME' -SnapshotName '$SNAPSHOT_NAME'\"" \
            || die "Snapshot failed"
        say "Snapshot '$SNAPSHOT_NAME' created on $HYPERV_HOST"
    fi
    echo
fi

# -- Step 4: Clock reset for §1692c out-of-hours demo ------------------------

if [[ "${NO_CLOCK:-0}" != "1" ]]; then
    say "Setting demo VM clock to 22:15 local for §1692c out-of-hours demo"
    warn "NTP is being DISABLED. Remember to re-enable after rehearsal:"
    warn "  sudo timedatectl set-ntp true"
    if sudo timedatectl set-ntp false 2>/dev/null && sudo timedatectl set-time 22:15:00 2>/dev/null; then
        echo "    clock set; current: $(date)"
    else
        warn "Could not set clock from this shell. Run on the demo VM:"
        warn "  sudo timedatectl set-ntp false && sudo timedatectl set-time 22:15:00"
    fi
    echo
fi

say "Demo-day bootstrap complete."
cat <<EOF

Next:
  - Open a fresh browser tab for each demo segment (see
    docs/Friday-Demo-Plan-2026-04-24.md §Operator reference).
  - Rehearse the full 45-min flow end to end.
  - After final rehearsal, take the 'rehearsal-ready' snapshot.
  - Demo morning: restore 'rehearsal-ready', re-run smoke-demo-path.sh,
    take 'pre-demo' snapshot, then begin.
EOF
