# InsideLLM — Edge VM Deployment Runbook (P1.C)

**Scope:** stand up the front-door edge router at `192.168.100.108/24` with
keepalived VIP `192.168.100.109`, then validate it terminates TLS, proxies
OIDC-authenticated traffic, and routes users to the correct
per-department backend.

**Prereqs:**
- Primary VM (`192.168.100.10`) already green (see `TestPlan_V1.md`).
- Debian 12 (Bookworm) cloud image staged on the Hyper-V host.
- OIDC provider (Azure AD or Okta) with a tenant + app registration.
- Time budget: ~20 minutes apply + smoke.

---

## 1. Workspace setup (your workstation)

Each VM is its own Terraform workspace — so we clone the repo into a
dedicated directory for the edge.

```powershell
# PowerShell on the host
cd C:\
git clone C:\Users\dmedina\Documents\Projects\InsideLLM C:\insidellm-edge
cd C:\insidellm-edge\terraform

# Copy the starter tfvars and edit
Copy-Item edge.tfvars.example ..\terraform.tfvars
# Fill in REPLACE markers — hyperv password, vm_switch_adapter,
# azure_ad_* or okta_*, ssh_public_key_path, edge_domain
notepad ..\terraform.tfvars
```

**Must-edit fields:**

| Field | Example | Why |
|---|---|---|
| `hyperv_password` | `"P@ssw0rd!"` | Host admin for WinRM |
| `vm_switch_adapter` | `"Ethernet"` | Must match your physical NIC |
| `edge_domain` | `"insidellm.corp.acme.com"` | TLS CN + OIDC redirect_uri |
| `sso_provider` + creds | `"azure_ad"` + client id/secret/tenant | OIDC validation |
| `fleet_primary_host` | `"192.168.100.10"` | Where gov-hub lives |
| `fleet_virtual_ip` | `"192.168.100.109"` | keepalived VIP — **never 192.168.100.108** (that's the edge's own NIC) |

---

## 2. Initialize + apply

```powershell
terraform init
terraform plan  -var-file="..\terraform.tfvars" -out edge.tfplan
# Review — expect a new `insidellm-edge` VM + cloud-init ISO + the thin
# docker-compose (oauth2-proxy + openresty + keepalived, nothing else).
terraform apply edge.tfplan
```

Post-deploy runs ~4–5 min on the edge VM (it's thin). Tail it:

```bash
ssh -i $env:USERPROFILE\.ssh\id_rsa insidellm@192.168.100.108
sudo tail -f /var/log/InsideLLM-deploy.log
# Wait for: "Inside LLM — READY"
```

---

## 3. Smoke tests (run on 192.168.100.108 unless noted)

### 3a. Only the three edge containers — nothing else

```bash
sudo docker ps --format '{{.Names}}'
# Expect exactly:
#   insidellm-oauth2-proxy
#   insidellm-openresty
#   insidellm-keepalived
# No litellm, no open-webui, no governance-hub (that's the primary's job)
```

### 3b. keepalived owns the VIP

```bash
ip addr show | grep -A1 '192.168.100.109'
# Expect: inet 192.168.100.109/32 scope global on eth0 (or whichever NIC)

# Alternative check — from the PRIMARY VM or workstation:
ping -c 3 192.168.100.109
# Should respond from the edge's MAC address.
```

### 3c. TLS terminates on the VIP

```bash
# From your workstation:
curl -vk https://192.168.100.109/ 2>&1 | grep -E "subject|CN=|issuer"
# Expect: CN matches edge_domain (or the self-signed default)
```

If DNS is set up, also verify the domain resolves:

```bash
dig +short insidellm.corp.example.com
# Should return 192.168.100.109
```

### 3d. OIDC redirect handshake

In a browser, open **`https://insidellm.corp.example.com/`** (or
`https://192.168.100.109/` if DNS isn't wired yet — you'll get a cert warning).

Expected flow:
1. 302 → your IdP login page
2. Sign in with an account that has a department claim matching one of the
   keys under `departments:` in `fleet.yaml` (e.g. `engineering`)
3. IdP bounces back to `https://<edge_domain>/oauth2/callback`
4. oauth2-proxy sets its session cookie
5. You land on the routed backend's Open WebUI page (e.g. `192.168.100.11`
   for `engineering`)

### 3e. Header forwarding (edge → backend trust)

From the backend VM (e.g. `192.168.100.11`):

```bash
docker logs insidellm-nginx --tail 50 | grep "X-User-Email"
# Expect: the most recent request carries
#   X-User-Email: <your email from the IdP>
#   X-Edge-Secret: <matches FLEET_EDGE_SECRET on both VMs>
```

If the secrets don't match, the backend refuses the request with 403 —
see Triage item 4 below.

### 3f. Register the edge in the fleet capability registry

From the primary VM:

```bash
KEY=$(grep -E '^LITELLM_MASTER_KEY=' /opt/InsideLLM/.env | cut -d= -f2-)
curl -sk -u insidellm-admin:$KEY \
  https://192.168.100.10/governance/api/v1/fleet/topology | jq '.edges'
# Expect: insidellm-edge (192.168.100.108) listed with capabilities oauth2_proxy,
# keepalived, openresty. If missing, wait ~60s for heartbeat; if still
# missing, see Triage #5.
```

---

## 4. If something breaks

| Symptom | Likely cause | Fast check |
|---|---|---|
| VM doesn't boot / no SSH | Cloud-init ISO failed | Hyper-V Manager → Console; look for `cloud-init` failure messages |
| `docker ps` shows nothing | cloud-init hadn't finished | `sudo systemctl status cloud-final.service` — if active (running), wait |
| `192.168.100.109` unreachable | keepalived not started | `sudo docker logs insidellm-keepalived` — often a VRRP authentication mismatch if two edges share a broadcast domain |
| TLS cert warning in browser | `self-signed` was the default | Expected — swap `edge_tls_source` to `letsencrypt` when the domain is DNS-reachable |
| Backend returns 403 | FLEET_EDGE_SECRET mismatch | `grep FLEET_EDGE_SECRET /opt/InsideLLM/.env` on both edge and backend VMs — must match byte-for-byte |
| OIDC loop-back fails | Redirect URI typo | IdP registration must list `https://<edge_domain>/oauth2/callback` literally — no trailing slash, no http:// |
| Department routing wrong | OIDC claim mismatch | `docker logs insidellm-oauth2-proxy --tail 50` — check the `groups` claim value vs the `departments:` key |

---

## 5. Add a second edge for keepalived HA (optional, post-smoke)

Deploy another edge at `10.0.0.101` with identical tfvars except:

```hcl
vm_name       = "insidellm-edge-2"
vm_hostname   = "insidellm-edge-2"
vm_static_ip  = "10.0.0.101/24"
# fleet_virtual_ip stays 192.168.100.109 — both edges share it
```

keepalived runs VRRP on the insidellm-internal broadcast domain and
negotiates master automatically. Verify both edges agree who's master:

```bash
# On 192.168.100.108
sudo docker logs insidellm-keepalived --tail 30 | grep -i master
# On 10.0.0.101
sudo docker logs insidellm-keepalived --tail 30 | grep -i master
# Exactly one should log "Entering MASTER state"
```

Failover test:

```bash
# Stop master (say, 192.168.100.108)
sudo docker stop insidellm-keepalived
# Within 3s, 10.0.0.101 should take over
# From workstation: ping 192.168.100.109 should stay responsive
```

---

## 6. Rollback

```powershell
cd C:\insidellm-edge\terraform
terraform destroy -var-file="..\terraform.tfvars"
# Removes the VM + cloud-init + VHDX. Primary + gateway VMs are untouched.
```

Safe to re-run `terraform apply` after destroy — the IP releases immediately.

---

## Sign-off checklist

Mark each row ✅ before calling the edge deployment complete:

- [ ] **3a.** Only 3 containers on the edge (no gov-hub / LiteLLM / OWUI)
- [ ] **3b.** keepalived owns `192.168.100.109` and it pings
- [ ] **3c.** TLS cert presented on `https://192.168.100.109/`
- [ ] **3d.** OIDC login → backend redirect works end-to-end
- [ ] **3e.** Backend logs show `X-User-Email` + valid `X-Edge-Secret`
- [ ] **3f.** Edge listed under `/governance/api/v1/fleet/topology`
