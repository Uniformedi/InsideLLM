# InsideLLM Browser Sidecar

**Product name:** InsideLLM Assist (internal codename: `page-assist-insidellm`)
**Repository:** [`Uniformedi/page-assist-insidellm`](https://github.com/Uniformedi/page-assist-insidellm)
**Base:** Thin enterprise fork of [Page Assist](https://github.com/n4ze3m/page-assist) (MIT)
**Status:** Scaffolding complete. Not yet built/signed/rolled out.

---

## What it is

A Chrome / Edge / Firefox extension that gives every employee an AI
sidebar in their browser — for chat, page summarization, selection
rewriting, and tool use — wired so it **only** talks to the InsideLLM
gateway on your VLAN. Everything that flows through the sidecar
inherits the platform's guardrails: DLP at the gateway, Humility
alignment, OPA policy, per-user budgets, hash-chained audit.

End users get "AI everywhere in the browser" without any of the usual
risks of shadow AI: pasting PII into public ChatGPT, employees
signing up for consumer accounts, data leaving your VLAN, per-user
API keys living in random browsers.

---

## Why a sidecar (vs. sending users to Open WebUI)

| Trigger | Open WebUI | Sidecar |
|---|---|---|
| "Summarize this 40-page PDF I'm reading in Chrome" | copy-paste into chat | right-click → summarize |
| "Rewrite this paragraph I'm typing in Confluence" | copy-paste out → edit → paste back | selection → side panel → accept |
| "What does this error on the logs dashboard mean?" | screenshot → upload → ask | right-click → ask AI |
| Shadow-AI friction | employees still tempted to use public tools for quick tasks | in-browser ubiquity removes the "it's faster elsewhere" excuse |

The sidecar is the **path of least resistance** for the 80% of
workflows that don't warrant opening a dedicated chat tab. Open WebUI
stays as the deep-work surface (long conversations, RAG over
documents, knowledge-base search). The sidecar is the everywhere-else
surface.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Employee's Chrome / Edge / Firefox                             │
│                                                                 │
│    ┌──────────────────────────────────────────────────────┐     │
│    │  InsideLLM Assist extension                          │     │
│    │    - Side panel chat                                 │     │
│    │    - Context menu actions                            │     │
│    │    - Page Q&A (reads current tab DOM as context)     │     │
│    │    - Config locked: only talks to gateway URL below  │     │
│    └─────────────────────┬────────────────────────────────┘     │
└──────────────────────────┼──────────────────────────────────────┘
                           │  HTTPS /v1/chat/completions
                           │  Authorization: Bearer <user-virtual-key>
                           ▼
┌─────────────────────────────────────────────────────────────────┐
│  InsideLLM gateway (on-prem VM / VLAN)                          │
│                                                                 │
│    Nginx (TLS terminator, path-routed /v1/ → LiteLLM)           │
│         │                                                       │
│    LiteLLM proxy:                                               │
│      1. dynamic_rate_limiter_v3 (per-key tpm/rpm + budget)      │
│      2. humility_prompt (SAIVAS prompt injection)               │
│      3. humility_guardrail (enforced rules; OPA-backed)         │
│      4. dlp_guardrail (inbound: PII/PHI/credentials/financials) │
│      5. forward to Anthropic / OpenAI / Bedrock / etc.          │
│      6. dlp_guardrail (outbound: redact echoed secrets)         │
│    Hash-chained audit → Governance Hub → fleet DB               │
└─────────────────────────────────────────────────────────────────┘
```

**The extension's HTTP base URL is pushed via Windows Group Policy
(`chrome.storage.managed`).** Users cannot change it from the
extension settings when lockdown mode is enabled — the config UI
hides the relevant controls. Every request carries a per-user LiteLLM
virtual key, also GPO-pushed. If an employee's key is revoked in the
Governance Hub, their next request fails with 401 — no tail of
cached auth.

---

## Configuration surface (`chrome.storage.managed`)

Configured via `policy/managed-schema.json` in the sidecar repo. Seven
settings:

| Setting | Type | Required | Meaning |
|---|---|---|---|
| `gatewayBaseUrl` | URL | ✓ | e.g. `https://insidellm.corp.example.com/v1` |
| `virtualApiKey` | string | ✓ | LiteLLM virtual key issued per user/team |
| `modelAllowlist` | array | | Model IDs surfaced in the picker (default: all the user's key can access) |
| `lockdown` | bool | default ✓ | Hide "add provider" / "edit endpoint" controls |
| `systemPrompt` | string | | Optional system prompt prepended to every chat |
| `temperatureCap` | number 0-2 | | Upper bound on the temperature slider |
| `pageQaEnabled` | bool | default ✓ | Allow "ask about this page" (reads current tab DOM) |
| `fileUploadEnabled` | bool | default ✓ | Allow attaching files to chats (DLP scans at gateway) |

All settings map 1:1 to the ADMX/ADML templates in `policy/gpo/` so
they're configurable via Windows Group Policy Management Console as
first-class GPO settings.

---

## Security posture

### What the sidecar does NOT have

- **No vendor API keys.** The extension never sees an Anthropic /
  OpenAI / Bedrock key. It only knows the InsideLLM gateway + a
  per-user virtual key.
- **No direct internet access to LLM providers.** Traffic must
  terminate at your gateway.
- **No local storage of conversation content** beyond Chrome's
  standard extension storage (IndexedDB on the user's profile). The
  authoritative audit record is on the gateway.
- **No way to disable DLP.** The callback runs at LiteLLM regardless
  of what the client sends — the extension can't opt out.

### What the sidecar DOES inherit

- **DLP gateway scanning** on every inbound message and outbound
  response (PII / PHI / credentials / financials patterns + any
  custom regex configured via `dlp_custom_patterns`).
- **Humility alignment** — requests that violate SAIVAS rules are
  rejected before the model sees them.
- **OPA industry overlays** (HIPAA, SOX, FERPA, GLBA, FDCPA, PCI-DSS)
  when `policy_engine_enable=true`.
- **Per-user budgets and rate limits** from the user's virtual key.
- **Hash-chained audit** of every request in the Governance Hub.

### Attack surface versus shadow AI

| Concern | Sidecar | Shadow AI (employee on ChatGPT.com) |
|---|---|---|
| Where does the prompt go? | Your gateway | OpenAI, outside VLAN |
| Where is the API key? | Per-user virtual key, on your Gateway | Employee's personal account |
| DLP | At gateway, unavoidable | Nothing |
| Audit trail | Yes, hash-chained | Nothing |
| Model allowlist enforcement | Yes | Nothing |
| Revocation | One click in Governance Hub | Impossible |
| Cost attribution | Per-user virtual-key billing | Zero visibility |

---

## Deployment guide (for administrators)

### Prerequisites

- Windows domain with GPO authority over target endpoints
- A scratch Windows machine with [Bun](https://bun.sh) installed (for
  the build step)
- An existing InsideLLM deployment reachable over HTTPS from endpoints
- An `ssh` + `scp` + `gh` CLI setup for the repo

### Step 1 — Clone + build

```powershell
gh repo clone Uniformedi/page-assist-insidellm
cd page-assist-insidellm

# One-time: apply overlay on top of upstream
.\scripts\fork.ps1

# Build
cd build\upstream
bun install
bun run build   # produces build/chrome-mv3/
```

### Step 2 — Sign

Sign the packed extension with your organization's signing key
(protect this key — changing it invalidates every installed instance
and triggers Chrome's "extension corrupted" dialog).

```powershell
# Generate once; keep the .pem in your secret manager
openssl genrsa -out signing-key.pem 2048

# Pack + sign
chrome.exe --pack-extension="C:\...\build\chrome-mv3" `
           --pack-extension-key="signing-key.pem"
# → produces chrome-mv3.crx (the signed installable)
```

### Step 3 — Host the update channel on the InsideLLM VM

```bash
# On your dev box:
scp build/upstream/build/chrome-mv3.crx \
    insidellm-admin@<vm>:/tmp/insidellm-assist.crx

# Render updates.xml:
sed -e 's|{{EXTENSION_ID}}|<your-extension-id>|' \
    -e 's|{{GATEWAY}}|insidellm.corp.example.com|' \
    update/updates.xml.tpl > updates.xml
scp updates.xml insidellm-admin@<vm>:/tmp/
```

On the VM:

```bash
sudo mv /tmp/insidellm-assist.crx /opt/InsideLLM/extensions/
sudo mv /tmp/updates.xml /opt/InsideLLM/extensions/

# The nginx snippet at update/nginx-snippet.conf shows how to expose
# /extensions/ as a public read-only path. Drop it into the nginx
# config template and redeploy, or add it to the live VM's nginx.conf.
```

After this, `https://<vm>/extensions/updates.xml` and
`https://<vm>/extensions/insidellm-assist.crx` are publicly readable.
Chrome update manifests don't carry authentication by design — the
extension is GPO-installed so only managed endpoints will fetch it.

### Step 4 — GPO deployment

1. In Group Policy Management Console, navigate to
   **Computer Configuration → Administrative Templates → Google →
   Google Chrome → Extensions**.
2. Enable **"Configure the list of force-installed apps and
   extensions"**. Add an entry:

   ```
   <extension-id>;https://<vm>/extensions/updates.xml
   ```

3. Import the InsideLLM Assist ADMX template:

   ```
   Copy policy/gpo/insidellm-assist.admx to
     %SystemRoot%\PolicyDefinitions\
   Copy policy/gpo/insidellm-assist.adml to
     %SystemRoot%\PolicyDefinitions\en-US\
   ```

4. Configure the seven settings under **Administrative Templates →
   InsideLLM → InsideLLM Assist**:
   - Gateway base URL
   - Virtual API key (per-group, rotate via Governance Hub)
   - Lockdown = Enabled
   - Model allowlist (comma-separated)
   - System prompt (optional)
   - Temperature cap (optional)
   - Page Q&A enabled
   - File upload enabled

5. Link the GPO to the target OU. Wait for Chrome's next policy
   refresh (~90 minutes by default) or run `gpupdate /force` on a test
   endpoint.

### Step 5 — Verify on a test endpoint

1. Open Chrome → `chrome://policy` — look for `ExtensionInstallForcelist` with your entry.
2. Open Chrome → `chrome://extensions` — the extension should appear,
   marked "Installed by your administrator".
3. Open the extension's side panel — it should show chat with the
   configured model picker, no "add provider" controls.
4. Send a test prompt. In the Governance Hub audit log, confirm the
   request shows up tagged with the virtual key's user identity.

---

## End-user guide

Once installed, the extension adds:

- **Side panel button** in the Chrome toolbar → opens chat panel
- **Context menu**: right-click selected text for rewrite / summarize /
  ask / translate
- **Keyboard shortcut**: `Ctrl+Shift+L` (configurable) opens the
  side panel

### Chat

The side panel behaves like a mini Open WebUI: conversation history
(stored locally in the browser profile), model picker (restricted to
the GPO allowlist), file attachments (if enabled).

### Page Q&A

Toggle "Ask about this page" in the side panel to include the current
tab's DOM as context. The DOM is sent to the gateway with the
message, so DLP scans it. Large pages are summarized client-side
before sending to stay within the model's token budget.

### What gets audited

Every message — inbound and outbound — is hash-chained and logged to
the Governance Hub with the user's identity (from the virtual key),
request timestamp, model, tokens consumed, DLP hits, Humility
decisions. Users should assume everything they type is audit-logged.
This is the platform's design, not a surprise.

---

## Troubleshooting

| Symptom | Check |
|---|---|
| Extension didn't install on endpoint | `chrome://policy` — is the force-install entry there? Is `gpupdate /force` done? |
| Extension installed but side panel empty | `chrome://extensions` → Details → Errors. Common: `gatewayBaseUrl` missing or wrong in managed policy |
| "Network error" in chat | Curl `https://<gateway>/v1/models` from the endpoint with the virtual key as `Authorization: Bearer`. If 401, key is revoked. If 502, gateway/nginx is down. |
| "DLP blocked your message" | Expected behavior — the user's message contained a pattern in the DLP ruleset. Tell them to rephrase. |
| "This model is not available" | The virtual key doesn't have access to the selected model. Check the key's `team_id` / `model_alias_allowed` in LiteLLM admin. |
| Key rotated but endpoints still using old one | Chrome caches `chrome.storage.managed` — force refresh with `gpupdate /force` + Chrome relaunch |

---

## Roadmap

- **Build automation** — a CI workflow that builds signed `.crx` on
  every release tag, hosted on GitHub Actions with the signing key in
  a secret
- **Electron/Tauri desktop shell** — for workflows outside the
  browser (IDE assistance, desktop app integration). Lower priority —
  the browser covers 80% of knowledge-worker AI use
- **macOS deployment profile** — the `managed-schema.json` works on
  Chrome / Edge across platforms; just need the per-OS distribution
  story (MDM on macOS, Chromebook enrollment, etc.)
- **Mobile** — Chrome extensions don't run on mobile. If mobile is a
  real need, a separate React Native app is the answer, not a port of
  this

---

## References

- Sidecar repository: [Uniformedi/page-assist-insidellm](https://github.com/Uniformedi/page-assist-insidellm)
- Upstream base: [n4ze3m/page-assist](https://github.com/n4ze3m/page-assist) (MIT-licensed)
- InsideLLM platform repository: [Uniformedi/InsideLLM](https://github.com/Uniformedi/InsideLLM)
- Related architecture docs:
  - [Guardrail architecture](architecture/guardrails.md)
  - [Policy library](architecture/policy-library.md)
  - [Attributions](ATTRIBUTIONS.md)
  - [Comparison vs peer AI gateways](comparison.md)
