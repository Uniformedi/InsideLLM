#!/usr/bin/env python3
"""Idempotently add LITELLM_MASTER_KEY to the governance-hub environment
in /opt/InsideLLM/docker-compose.yml on the primary. The stale compose
render (pre-Stream A) was missing this, which broke break-glass."""

import re
import sys

P = "/opt/InsideLLM/docker-compose.yml"
t = open(P).read()

m = re.search(r"(  governance-hub:.*?environment:\n)(.*?)(^    [a-z])",
              t, flags=re.DOTALL | re.MULTILINE)
if not m:
    print("governance-hub env block not found", file=sys.stderr)
    sys.exit(1)

env = m.group(2)
if "LITELLM_MASTER_KEY:" in env:
    print("already has LITELLM_MASTER_KEY")
    sys.exit(0)

new_env = env.rstrip() + "\n" + '      LITELLM_MASTER_KEY: "${LITELLM_MASTER_KEY}"' + "\n"
t = t[:m.start(2)] + new_env + t[m.end(2):]
open(P, "w").write(t)
print("added LITELLM_MASTER_KEY to governance-hub env")
