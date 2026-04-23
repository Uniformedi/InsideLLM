---
title: InsideLLM Assist — One-Off Local Install
codename: page-assist-insidellm
audience: Developers / pilot testers
status: Pre-distribution (no GPO, no .crx hosting)
---

# InsideLLM Assist — One-Off Local Install

How to install the `page-assist-insidellm` extension on a single
machine for development, demo, or a pilot — without going through the
full GPO + self-host update channel.

Three options, ordered by how close they are to a production install.
Pick **Option A** unless you have a reason not to.

---

## Option A — Load unpacked (recommended)

Fastest path. No signing, no `.crx`, no policy required to get it
running. Survives Chrome restarts. You'll see a "Disable developer
mode extensions" banner on every Chrome startup — that's expected.

### Build

```bash
git clone https://github.com/Uniformedi/page-assist-insidellm.git
cd page-assist-insidellm
./scripts/fork.sh           # Linux/macOS
# .\scripts\fork.ps1        # Windows PowerShell

cd build/upstream
bun install
bun run build               # Chrome MV3 build
```

Output: `build/upstream/build/chrome-mv3/`

### Install in Chrome

1. Open `chrome://extensions`.
2. Toggle **Developer mode** (top-right).
3. Click **Load unpacked**.
4. Select `build/upstream/build/chrome-mv3/`.

The extension's ID is shown on the card — **copy it**, you'll need it
for the policy file in the next step.

### (Optional) Seed managed config

Without a managed-policy file, the extension falls back to its
in-extension settings UI — fine for a quick demo. For lockdown-mode
behavior (gateway URL + virtual key pre-seeded, controls hidden), drop
a Chrome managed-policy file:

**Linux:**

```bash
sudo mkdir -p /etc/opt/chrome/policies/managed
sudo tee /etc/opt/chrome/policies/managed/insidellm-assist.json >/dev/null <<'EOF'
{
  "3rdparty": {
    "extensions": {
      "<EXTENSION_ID_FROM_chrome://extensions>": {
        "gatewayBaseUrl": "https://insidellm.corp.example.com/v1",
        "virtualApiKey": "sk-...",
        "lockdown": true,
        "pageQaEnabled": true
      }
    }
  }
}
EOF
```

**macOS:** drop the same JSON at
`/Library/Managed Preferences/com.google.Chrome.plist` (convert to
plist) — easier to use `defaults write` per Google's Chrome Enterprise
docs.

**Windows:** use `regedit` under
`HKLM\Software\Policies\Google\Chrome\3rdparty\extensions\<ID>\policy`,
or import the ADMX templates from `policy/` in the extension repo.

Restart Chrome and visit `chrome://policy` to confirm the values
loaded under "Extension policies".

---

## Option B — Pack into `.crx` and side-load

Use this when you want to test the actual `.crx` artifact (signing
key, extension ID stability, update flow) — not when you just want it
running. On a clean Chrome install on Linux/Mac, drag-installing a
`.crx` is **blocked by default**: you must first whitelist the
extension ID via managed policy. So this is a managed test box
exercise, not a "no setup" install.

### Pack

```bash
# One-time signing key. Keep it safe — it pins the extension ID forever.
openssl genrsa -out ~/insidellm-assist.pem 2048

google-chrome --pack-extension=build/upstream/build/chrome-mv3 \
              --pack-extension-key=~/insidellm-assist.pem
```

Produces `build/upstream/build/chrome-mv3.crx`.

### Allow self-install

Add to your managed-policy JSON (alongside the per-extension config
from Option A):

```json
{
  "ExtensionInstallSources": ["file:///*"],
  "ExtensionInstallAllowlist": ["<EXTENSION_ID>"]
}
```

Restart Chrome, then drag the `.crx` onto `chrome://extensions`.

---

## Option C — Firefox (no policy dance)

Fastest if you want to bypass Chrome's policy requirements entirely.
The install is **temporary** — cleared on browser restart.

```bash
bun run build:firefox
```

In Firefox:

1. Open `about:debugging`.
2. Click **This Firefox**.
3. **Load Temporary Add-on…**.
4. Pick the `manifest.json` inside the firefox build directory.

---

## Verifying it works

Regardless of option:

1. Click the extension icon → side panel should open.
2. Right-click on any web page → "InsideLLM Assist" actions in the menu.
3. Trigger a chat → check the InsideLLM gateway logs (LiteLLM proxy)
   for the inbound request carrying your virtual key.

If the request never reaches the gateway, the most common causes are
(a) wrong `gatewayBaseUrl` (trailing slash, missing `/v1`), (b)
managed policy not actually loaded — re-check `chrome://policy`, (c)
the virtual key was revoked or the user's budget is exhausted (gateway
returns 401 / 429).

---

## What this is *not*

This document covers a single-machine install. It does **not** cover:

- Hosting the `.crx` + `updates.xml` self-update channel on the
  InsideLLM nginx VM (see the deployment guide in the main repo).
- Chrome Enterprise Group Policy rollout to many endpoints (see
  `policy/` in `page-assist-insidellm` for ADMX/ADML templates).
- Firefox enterprise policy (`policies.json`) for sustained Firefox
  installs.
