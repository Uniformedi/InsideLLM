# InsideLLM — Okta Implementation Instructions for Organization

**Audience:** Organization Okta administrator
**Prepared by:** Uniformedi LLC
**Platform version:** 3.1
**Date:** 2026-04-16
**Estimated effort on your side:** 30–45 minutes

This document describes exactly what Organization needs to configure in your
Okta tenant so that InsideLLM uses Okta as its single sign-on source.
No changes to your existing Okta tenant's global policies are required.
Everything below is scoped to a single new OIDC application.

---

## 1. What gets created in your Okta tenant

| Object | Quantity | Purpose |
|---|---|---|
| OIDC Web Application | 1 | Authenticates all InsideLLM users |
| Custom claim (authorization server) | 2 | `groups` + `department` emitted in tokens |
| Security groups | 3 (baseline) | Admin, View, Approve roles |
| Department groups (optional) | one per department | Drives per-department LLM routing |
| User assignments | N | Users mapped to groups |

No new authorization servers are needed. No changes to existing apps.

---

## 2. Information Uniformedi has already sent you

You should already have received the following from our team:

1. The edge VM FQDN we will deploy, e.g. `insidellm.organization.internal`
2. The exact redirect URI: `https://insidellm.organization.internal/oauth2/callback`
3. The sign-out URI: `https://insidellm.organization.internal/oauth2/sign_out`
4. Our organization's TLS CA public cert (for certs via `custom` mode) — only if your PKI team is issuing the cert

If any of these are missing, request them before starting.

---

## 3. Step-by-step

### Step 3.1 — Create the OIDC Application

1. Log into Okta Admin Console (`https://<your-org>-admin.okta.com`).
2. **Applications → Applications → Create App Integration.**
3. Select **OIDC – OpenID Connect** → **Web Application** → Next.

**General Settings:**
- App integration name: `InsideLLM`
- Logo (optional): upload if available
- Grant type: `Authorization Code` (default, leave checked)
- Sign-in redirect URIs: `https://insidellm.organization.internal/oauth2/callback`
- Sign-out redirect URIs: `https://insidellm.organization.internal/oauth2/sign_out`
- Controlled access: **Limit access to selected groups** (we will create them in Step 3.3)

Click **Save.**

### Step 3.2 — Record credentials

On the next screen you will see:

- **Client ID** — copy this. Not a secret but needed by Uniformedi.
- **Client Secret** — click **Show** and copy immediately. This will be revealed only once. Transfer via your approved secret-sharing channel (1Password / Bitwarden / encrypted email). Do **not** paste in chat or unencrypted email.

Send both to the Uniformedi deployment contact.

### Step 3.3 — Create role groups

**Directory → Groups → Add Group** (three times):

| Group name | Description |
|---|---|
| `InsideLLM-Admin` | Full CRUD on InsideLLM governance (except change approvals) |
| `InsideLLM-View` | Read-only access to InsideLLM admin pages |
| `InsideLLM-Approve` | Approve/reject change proposals (Segregation of Duties) |

Prefix may be adjusted to your naming convention (e.g., `Organization-InsideLLM-*`); please notify Uniformedi if you change the prefix so our config matches.

### Step 3.4 — Create department groups (optional but recommended)

If you want each Organization department routed to its own InsideLLM gateway
(recommended — lets each department have its own LLM budget, DLP rules,
and audit trail), create one group per department:

- `InsideLLM-Dept-Engineering`
- `InsideLLM-Dept-Legal`
- `InsideLLM-Dept-Operations`
- `InsideLLM-Dept-Finance`
- `InsideLLM-Dept-Sales`
- (…etc. — one per department you want isolated)

Alternatively, if your user profiles already carry a `department` attribute (standard Okta schema), you can skip the groups and tell Uniformedi to use the attribute directly. Either works; groups are easier to manage in bulk.

### Step 3.5 — Assign the app to the groups

1. Open the **InsideLLM** application you created.
2. **Assignments** tab → **Assign → Assign to Groups.**
3. Assign to every group from Steps 3.3 and 3.4.

At this point no one can log into InsideLLM yet — you still need to add users to the groups. We recommend starting with:
- 1–2 users in `InsideLLM-Admin`
- 2–3 users in `InsideLLM-Approve` (different people from Admin for SoD)
- Broad assignment to `InsideLLM-View` for all users who need basic access
- Users in their respective `InsideLLM-Dept-*` group

### Step 3.6 — Configure claims

InsideLLM needs two claims in the ID token: `groups` and `department`.

1. **Security → API → Authorization Servers.**
2. Open your default authorization server (`default`).
3. **Claims** tab → **Add Claim.**

**Claim A — `groups`:**

| Field | Value |
|---|---|
| Name | `groups` |
| Include in token type | ID Token, Always |
| Value type | Groups |
| Filter | Matches regex · `^InsideLLM-.*` |
| Include in | ID token + userinfo |

Click **Create.**

**Claim B — `department` (group-based):**

If you used department groups (Step 3.4), create a second claim that extracts the department name from the user's InsideLLM-Dept-* group:

| Field | Value |
|---|---|
| Name | `department` |
| Value type | Expression |
| Value | `String.substringAfter(String.join(",", Arrays.array(user.group.name.filter(g -> g.startsWith("InsideLLM-Dept-")))), "InsideLLM-Dept-")` |
| Include in | ID token + userinfo |

(If the expression syntax is rejected by your Okta tenant — some orgs restrict custom expressions — use a Groups claim with filter `^InsideLLM-Dept-.*` and we will parse the prefix on our side.)

**Claim B (alternative — attribute-based):**

If you have a `department` attribute on user profiles:

| Field | Value |
|---|---|
| Name | `department` |
| Value type | Expression |
| Value | `user.department` |
| Include in | ID token + userinfo |

---

## 4. Sign-on policy (optional)

If Organization enforces MFA or other sign-on rules, they apply automatically to the InsideLLM app once it is assigned to your org-wide sign-on policy. No per-app configuration is needed. If you want InsideLLM to require *stronger* MFA (e.g., hardware key only for Admin users), attach a dedicated sign-on policy to the InsideLLM app:

1. Application → **Sign On** tab → **Edit**.
2. Add a rule: "If user is member of `InsideLLM-Admin`, require FIDO2/WebAuthn."

---

## 5. Verification

Once Uniformedi has completed the edge deployment (we will notify you), you can verify the integration:

1. Open an incognito browser window.
2. Navigate to `https://insidellm.organization.internal`.
3. Expect: immediate redirect to Okta login.
4. Log in as a test user who is a member of `InsideLLM-View`.
5. Expect: redirected back to InsideLLM; Open WebUI interface loads; user's email shown in top-right.
6. If the user is also in `InsideLLM-Dept-Engineering`, the session should connect to the Engineering LLM gateway (confirmed by the URL bar showing the gateway hostname, or by asking the chat "which department gateway am I on?" — InsideLLM responds with the gateway name).

**If the login loop fails** (repeated Okta redirects): re-check the redirect URI exactly matches `https://insidellm.organization.internal/oauth2/callback`, including scheme, host, and port. No trailing slash.

**If groups are missing from the token:** re-check the claim filter regex and token type (ID Token) in Step 3.6.

---

## 6. What Uniformedi will configure on our side

For reference, these are the InsideLLM-side settings that consume your Okta setup (you do not touch these):

```
sso_provider       = "okta"
okta_domain        = "<your-org>.okta.com"
okta_client_id     = "<from Step 3.2>"
okta_client_secret = "<from Step 3.2 — via secret channel>"

edge_domain        = "insidellm.organization.internal"

oidc_admin_group_ids    = ["InsideLLM-Admin"]
oidc_view_group_ids     = ["InsideLLM-View"]
oidc_approver_group_ids = ["InsideLLM-Approve"]
```

The three `oidc_*_group_ids` lists take either group names or group object IDs — whichever your Okta tenant emits in the `groups` claim. Uniformedi will confirm which during Phase 1 testing and adjust if needed.

---

## 7. DNS and certificate prerequisites

Separate from Okta but required for the deployment to work:

1. **DNS**: your IT team creates an A record `insidellm.organization.internal` → `<edge VIP>` (Uniformedi will provide the IP before cutover).
2. **TLS certificate**: three options, pick one:
   - **Option A — Let's Encrypt** (simplest, free, requires public DNS + port 80 reachable for HTTP-01 challenge). If `insidellm.organization.internal` is internal-only, use Option B or C.
   - **Option B — Your corporate CA** (recommended for on-prem). Your PKI team issues a cert for `insidellm.organization.internal`, sends PEM files to Uniformedi; we install them at deploy time. Browser shows valid lock icon to all Organization users who trust your internal CA.
   - **Option C — Self-signed** (demo only). Users get a browser warning they must bypass. Not recommended for production.
3. **Firewall** — the edge VM must be reachable on TCP/443 from every Organization user's subnet, and outbound to `<your-org>.okta.com` on 443 for the Okta handshake. No other inbound ports required.

---

## 8. Timeline

| Step | Owner | Estimated time |
|---|---|---|
| Create OIDC app + groups + claims | Organization Okta admin | 30 min |
| Assign initial users | Organization Okta admin | 15 min |
| Deliver credentials to Uniformedi | Organization Okta admin | 5 min |
| DNS A record creation | Organization IT | 15 min |
| Certificate issuance (if Option B) | Organization PKI team | 1-3 business days |
| Uniformedi edge deployment | Uniformedi | 45 min |
| End-to-end test | Joint | 30 min |

Total: **same day** if using Let's Encrypt or self-signed. **2–3 business days** if waiting on a corporate cert.

---

## 9. Questions / escalation

- Okta config questions → Organization Okta admin's usual Okta support channel
- Integration questions → Uniformedi deployment contact
- Security review questions → `docs/SecurityArchitecture.md` (provided separately)

---

## 10. Post-deployment lifecycle

### Adding new users
- Assign them to the appropriate Okta groups (`InsideLLM-View` plus any role/department groups).
- They can log in immediately; no InsideLLM-side action needed. InsideLLM reads the Okta token at each login.

### Removing users
- Remove from the Okta groups or deactivate the Okta user.
- Their next request to InsideLLM fails OIDC and they are locked out. Active sessions expire at the Redis session-store TTL (default 24 hours).

### Changing a user's role
- Move them between `InsideLLM-Admin`/`InsideLLM-View`/`InsideLLM-Approve`. The change takes effect on their next login (or within the session TTL).

### Rotating the client secret
- Okta admin generates a new client secret on the InsideLLM app → send to Uniformedi → Uniformedi updates the deployment env → rolling restart of edge + primary. Zero-downtime rotation procedure is in the operator runbook.

### Auditing who accessed what
- InsideLLM emits a hash-chained audit log entry for every authenticated action. Pulling together Okta sign-in logs and InsideLLM audit gives a full chain from Okta identity → InsideLLM activity.

---

End of document. Contact your Uniformedi deployment lead with any
clarifications before beginning Step 3.1.
