#!/usr/bin/env python3
"""Idempotently add RBAC env vars to governance-hub in /opt/InsideLLM/docker-compose.yml"""
import re, sys
p = "/opt/InsideLLM/docker-compose.yml"
t = open(p).read()
# Locate governance-hub environment block
m = re.search(r"(  governance-hub:.*?environment:\n)(.*?)(^    [a-z])",
              t, flags=re.DOTALL | re.MULTILINE)
if not m:
    print("governance-hub block not found"); sys.exit(1)

env_body = m.group(2)
additions = []
if "LITELLM_MASTER_KEY:" not in env_body:
    additions.append('      LITELLM_MASTER_KEY: "${LITELLM_MASTER_KEY}"')
if "GOVERNANCE_HUB_AD_VIEW_GROUPS" not in env_body:
    additions.append('      GOVERNANCE_HUB_AD_VIEW_GROUPS: "InsideLLM-View"')
if "GOVERNANCE_HUB_AD_APPROVER_GROUPS" not in env_body:
    additions.append('      GOVERNANCE_HUB_AD_APPROVER_GROUPS: "InsideLLM-Approve"')

if not additions:
    print("already patched"); sys.exit(0)

new_env = env_body.rstrip() + "\n" + "\n".join(additions) + "\n"
t = t[:m.start(2)] + new_env + t[m.end(2):]
open(p, "w").write(t)
print(f"added {len(additions)} env vars")
