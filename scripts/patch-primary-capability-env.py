#!/usr/bin/env python3
"""Hot-patch /opt/InsideLLM/docker-compose.yml on the primary to add the
Stream A capability-publishing env vars that were missing in the stale
render. Idempotent."""

import re
import sys

P = "/opt/InsideLLM/docker-compose.yml"
t = open(P).read()

# Find governance-hub environment block
m = re.search(r"(  governance-hub:.*?environment:\n)(.*?)(^    [a-z])",
              t, flags=re.DOTALL | re.MULTILINE)
if not m:
    print("governance-hub env block not found", file=sys.stderr)
    sys.exit(1)

env = m.group(2)
adds: list[str] = []
if "VM_ROLE:" not in env:
    adds.append('      VM_ROLE: "primary"')
if "FLEET_EDGE_SECRET:" not in env:
    adds.append('      FLEET_EDGE_SECRET: "${FLEET_EDGE_SECRET}"')
if "CAP_LITELLM_ENDPOINT:" not in env:
    adds.append('      CAP_LITELLM_ENDPOINT: "http://litellm:4000/v1"')
if "CAP_OPEN_WEBUI_ENDPOINT:" not in env:
    adds.append('      CAP_OPEN_WEBUI_ENDPOINT: "http://open-webui:8080"')
if "CAP_GRAFANA_ENDPOINT:" not in env:
    adds.append('      CAP_GRAFANA_ENDPOINT: "http://grafana:3000"')
if "CAP_LOKI_ENDPOINT:" not in env:
    adds.append('      CAP_LOKI_ENDPOINT: "http://loki:3100"')
if "CAP_UPTIME_KUMA_ENDPOINT:" not in env:
    adds.append('      CAP_UPTIME_KUMA_ENDPOINT: "http://uptime-kuma:3001"')
if "CAP_DOCFORGE_ENDPOINT:" not in env:
    adds.append('      CAP_DOCFORGE_ENDPOINT: "http://docforge:3000"')

if not adds:
    print("already patched")
    sys.exit(0)

new_env = env.rstrip() + "\n" + "\n".join(adds) + "\n"
t = t[:m.start(2)] + new_env + t[m.end(2):]
open(P, "w").write(t)
print(f"added {len(adds)} env vars to governance-hub")

# Also add FLEET_EDGE_SECRET to .env if missing
env_file = "/opt/InsideLLM/.env"
e = open(env_file).read()
if "FLEET_EDGE_SECRET=" not in e:
    import secrets
    e += f"\nFLEET_EDGE_SECRET={secrets.token_hex(24)}\n"
    open(env_file, "w").write(e)
    print("added FLEET_EDGE_SECRET to .env")
