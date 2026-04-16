# Claude Code CLI on every InsideLLM VM

Each InsideLLM VM (except bare-bones roles like `edge`, `voice`, `storage`)
auto-installs the Claude Code CLI for the admin user. SSH into any node
and you have an AI assistant scoped to that VM's filesystem, ready to
troubleshoot.

This is **ops tooling**, not an end-user feature. Operator logs in once
per VM via OAuth; their credentials live in `~/.claude/` under the admin
account and never leave the VM.

---

## What gets installed

- **Binary:** `~/.local/bin/claude` under the `insidellm-admin` user
- **Install method:** Official `claude.ai/install.sh` script
- **Context seed:** `/opt/InsideLLM/CLAUDE.md` pre-filled with hostname,
  role, department, fleet primary — so the first Claude session starts
  with real VM context without you typing it in

Gated by `claude_code_enable` (default `true`). Auto-skipped for
`vm_role` in `edge`, `voice`, `storage`.

---

## First login (once per VM)

```bash
ssh insidellm-admin@<vm-ip>
cd /opt/InsideLLM
claude login
# → prints a URL; open in browser, auth with your Anthropic account
# → paste the code back into the terminal
```

Credentials stored at `~/.claude/`, persist across sessions, per-VM.

---

## Daily usage

```bash
ssh insidellm-admin@<vm-ip>
cd /opt/InsideLLM
claude
```

Drops you into an interactive Claude Code session with:

- Working directory scoped to `/opt/InsideLLM` (compose, .env, data/, logs/)
- Pre-loaded context from `/opt/InsideLLM/CLAUDE.md`
- Access to `Bash`, `Read`, `Edit`, `Glob`, `Grep` tools
- Per-VM memory at `~/.claude/projects/<cwd>/memory/` — builds institutional knowledge over time

---

## "Nested Dans" pattern

With one VM per department / role, each SSH'd-in Claude session is its
own instance with:

- A focused scope (one VM's state, not the whole fleet)
- Its own accumulated memory
- Its own token usage (no interference across VMs)

Useful when troubleshooting:

- `Dan@10.0.0.9`  — primary's governance, central DB sync, Grafana
- `Dan@10.0.0.11` — engineering gateway LiteLLM quirks, dept-specific DLP
- `Dan@edge`      — routing.lua, oauth2-proxy, keepalived

Work cross-fleet changes through Git + `scripts/Deploy-Fleet.ps1` from
your workstation. Each VM's Claude is for its own VM.

---

## Security posture

| Risk | Mitigation |
|---|---|
| Credential sprawl | OAuth session tokens, not raw API keys. Revoke per-VM via Anthropic Console. |
| Claude accessing secrets | `/opt/InsideLLM/.env` is `chmod 600 root` — Claude would need `sudo`. Budget accordingly. |
| Exfiltration via chat context | Direct-to-Anthropic path bypasses InsideLLM DLP. If this concerns you, set `ANTHROPIC_BASE_URL=http://litellm:4000` in `/etc/profile.d/claude-code.sh` to route through LiteLLM (inherits DLP + Humility + audit). |
| Token theft from `~/.claude/` | SSH key auth gates access. Rotate SSH keys quarterly. |

---

## Routing ops through LiteLLM (optional)

Default install points Claude Code at `api.anthropic.com` directly. To
route ops sessions through this VM's own LiteLLM gateway instead (so
they show up in the governance audit alongside user chat traffic):

```bash
# On the VM, as root:
cat > /etc/profile.d/claude-code-litellm.sh <<'EOF'
export ANTHROPIC_BASE_URL="http://litellm:4000"
export ANTHROPIC_AUTH_TOKEN="<a-dedicated-ops-virtual-key>"
EOF
chmod 644 /etc/profile.d/claude-code-litellm.sh
```

Mint the ops virtual key via the LiteLLM admin UI at
`https://<vm>/litellm/ui` with `user_id=ops:<hostname>`, appropriate
model allowlist, and a daily budget cap.

Not the default because OAuth login is simpler and most operators don't
need every Claude Code call DLP-scanned — it's Dan troubleshooting Dan's
own box.

---

## Rollback

To skip install on a specific VM:

```hcl
# terraform.tfvars
claude_code_enable = false
```

To remove on a running VM:

```bash
sudo -u insidellm-admin rm -rf ~insidellm-admin/.local/bin/claude ~insidellm-admin/.claude
```
