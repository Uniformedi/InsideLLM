#!/usr/bin/env python3
import sys
p = '/opt/InsideLLM/docker-compose.yml'
t = open(p).read()
# Double the backslash in uniformedi\dmedina for YAML-safe escape
bad = 'uniformedi\\dmedina'
good = 'uniformedi\\\\dmedina'
if bad in t and good not in t:
    t = t.replace(bad, good)
    open(p, 'w').write(t)
    print('fixed hyperv_user escape')
else:
    print('no change needed')

# Add OPENAI_API_BASE_URLS / KEYS if missing
if 'OPENAI_API_BASE_URLS' not in t:
    import re
    mk = None
    for line in open('/opt/InsideLLM/.env'):
        if line.startswith('LITELLM_MASTER_KEY='):
            mk = line.strip().split('=', 1)[1]
    if mk:
        inject = f'      OPENAI_API_BASE_URLS: "http://litellm:4000/v1"\n      OPENAI_API_KEYS: "{mk}"\n'
        t2 = re.sub(
            r'(OPENAI_API_KEY: "[^"]*"\n)',
            r'\1' + inject, t, count=1)
        if 'ENABLE_OPENAI_API' not in t2:
            t2 = t2.replace('OPENAI_API_BASE_URL:', 'ENABLE_OPENAI_API: "true"\n      OPENAI_API_BASE_URL:', 1)
        open(p, 'w').write(t2)
        print('added OPENAI_API_BASE_URLS/KEYS + ENABLE_OPENAI_API')
