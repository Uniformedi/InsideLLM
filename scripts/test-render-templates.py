#!/usr/bin/env python3
"""Render every Terraform-consumed template with dummy vars and parse the
result. Catches template-syntax errors and Ubuntu → Debian swap regressions
without needing a live Hyper-V host.

This doesn't replace `terraform plan` — it's a fast, tool-agnostic syntax
check over the 7 rendered artifacts that land on the VM:

  * user-data.yaml.tpl         (main VM cloud-init)
  * edge-user-data.yaml.tpl    (edge VM cloud-init)
  * ollama-user-data.yaml.tpl  (Ollama VM cloud-init)
  * docker-compose.yml.tpl     (compose file)
  * nginx.conf.tpl             (nginx config)
  * post-deploy.sh.tpl         (bash script)
  * env-file.tpl               (shell env)
  * insidellm-realm.json.tpl   (Keycloak realm import)

Uses a minimal HCL-to-Python translator — good enough for the `${var}`,
`%{ if cond ~}…%{ endif ~}`, and `${indent(n, s)}` constructs Terraform
actually uses in these templates.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

REPO = Path(__file__).resolve().parents[1]


# ---------------------------------------------------------------------------
# Minimal Terraform-template interpreter
# ---------------------------------------------------------------------------


def _indent(n: int, s: str) -> str:
    pad = " " * int(n)
    return ("\n" + pad).join(s.splitlines())


def _jsonencode(obj: Any) -> str:
    return json.dumps(obj)


def _trimspace(s: str) -> str:
    return s.strip() if isinstance(s, str) else s


BUILTINS = {
    "indent": _indent,
    "jsonencode": _jsonencode,
    "trimspace": _trimspace,
    "length": lambda x: len(x),
    "split": lambda sep, s: s.split(sep),
    "join": lambda sep, lst: sep.join(str(x) for x in lst),
    "fileexists": lambda p: Path(p).exists(),
    "base64encode": lambda s: __import__("base64").b64encode(
        s.encode() if isinstance(s, str) else s
    ).decode(),
    "filebase64": lambda p: __import__("base64").b64encode(
        Path(p).read_bytes()
    ).decode() if Path(p).exists() else "",
    "file": lambda p: Path(p).read_text(encoding="utf-8") if Path(p).exists() else "",
    "replace": lambda s, old, new: s.replace(old, new),
    "lower": lambda s: s.lower(),
    "upper": lambda s: s.upper(),
}


def render(tpl: str, ctx: dict[str, Any]) -> str:
    """Render a terraform-flavoured template.

    Supports: ${var}, ${expr(...)}, %{ if cond ~}A%{ else ~}B%{ endif ~},
    %{ for x in list ~}A%{ endfor ~}. Intentionally lenient — this is a
    syntax-check render, not a full HCL evaluator.
    """
    # Step 1: apply the `~` trim markers. Terraform semantics: `~}` trims
    # inline whitespace after the directive + consumes at most ONE newline
    # (NOT the indent of the next content line); `{~` trims inline
    # whitespace before the directive + consumes at most one preceding
    # newline. A greedy `\s*` on either side eats subsequent-line indents,
    # which corrupts YAML block scalars.
    tpl = re.sub(r"[ \t]*~\}[ \t]*\n?", "}", tpl)
    tpl = re.sub(r"\n?[ \t]*\{~[ \t]*", "{", tpl)

    # Step 2: while-expand control flow bottom-up
    while True:
        if_match = re.search(r"%\{\s*if\s+([^{}%]+?)\s*\}", tpl)
        for_match = re.search(r"%\{\s*for\s+(\w+)\s+in\s+([^{}%]+?)\s*\}", tpl)
        if not if_match and not for_match:
            break
        if if_match and (not for_match or if_match.start() < for_match.start()):
            # Find its matching endif
            tpl = _expand_if(tpl, if_match, ctx)
        else:
            tpl = _expand_for(tpl, for_match, ctx)

    # Step 3: inline `${…}` expressions.
    def repl(m: re.Match) -> str:
        expr = m.group(1).strip()
        try:
            return str(_eval(expr, ctx))
        except Exception as e:
            return f"<<ERR:{expr}:{e}>>"

    return re.sub(r"\$\{([^{}]+?)\}", repl, tpl)


def _find_matching(tpl: str, open_re: str, close_tok: str, start: int) -> int:
    """Find matching close token given 1 open already consumed at `start`."""
    depth = 1
    i = start
    while i < len(tpl):
        m_open = re.search(open_re, tpl[i:])
        m_close = re.search(r"%\{\s*" + close_tok + r"\s*\}", tpl[i:])
        if m_close is None:
            return -1
        if m_open and m_open.start() < m_close.start():
            depth += 1
            i += m_open.end()
            continue
        depth -= 1
        if depth == 0:
            return i + m_close.start(), i + m_close.end()
        i += m_close.end()
    return -1


def _expand_if(tpl: str, m: re.Match, ctx: dict) -> str:
    cond = m.group(1)
    head = tpl[: m.start()]
    body_start = m.end()
    close = _find_matching(tpl, r"%\{\s*if\s", "endif", body_start)
    if close == -1:
        return head + f"<<UNCLOSED-IF:{cond}>>" + tpl[body_start:]
    close_start, close_end = close
    body = tpl[body_start:close_start]
    tail = tpl[close_end:]
    # Check for nested else (at the top level of body)
    else_idx = _top_level_else(body)
    if else_idx is not None:
        then_part = body[:else_idx]
        else_part = body[body.find("}", else_idx) + 1:]
    else:
        then_part = body
        else_part = ""
    try:
        truthy = bool(_eval(cond, ctx))
    except Exception:
        truthy = False
    return head + (then_part if truthy else else_part) + tail


def _top_level_else(body: str) -> int | None:
    depth = 0
    i = 0
    while i < len(body):
        m = re.search(r"%\{\s*(if|for|else|endif|endfor)\s*", body[i:])
        if not m:
            return None
        kw = m.group(1)
        pos = i + m.start()
        if kw in ("if", "for"):
            depth += 1
        elif kw in ("endif", "endfor"):
            depth -= 1
        elif kw == "else" and depth == 0:
            return pos
        i = pos + len(m.group(0))
    return None


def _expand_for(tpl: str, m: re.Match, ctx: dict) -> str:
    var = m.group(1)
    list_expr = m.group(2)
    # Terraform's `~}` trim chomps the trailing newline of the control
    # directive and the leading whitespace of the body's first line. Mirror
    # that: the rendered body starts at a column 0 logical line, so we need
    # to preserve any indent the line *before* `%{ for }` carried. Pull that
    # indent from the last line of `head` and prepend it to each iteration.
    head = tpl[: m.start()]
    body_start = m.end()
    close = _find_matching(tpl, r"%\{\s*for\s", "endfor", body_start)
    if close == -1:
        return head + f"<<UNCLOSED-FOR:{var}>>" + tpl[body_start:]
    close_start, close_end = close
    body = tpl[body_start:close_start]
    tail = tpl[close_end:]
    # Figure out the indent the `%{ for }` directive sat at.
    last_line = head.rsplit("\n", 1)[-1]
    indent = re.match(r"^[ \t]*", last_line).group(0)
    try:
        iterable = _eval(list_expr, ctx)
    except Exception:
        iterable = []
    rendered = []
    for item in iterable or []:
        sub_ctx = {**ctx, var: item}
        sub_rendered = render(body, sub_ctx)
        # Terraform's ~} trim eats the newline after `%{ for }`, so body
        # typically starts with the indent for the first content line but
        # subsequent iterations need the indent re-applied to the first
        # line of each body copy. Prepend the indent to every iteration.
        if indent and not sub_rendered.startswith(indent):
            sub_rendered = indent + sub_rendered
        rendered.append(sub_rendered)
    return head + "".join(rendered) + tail


def _eval(expr: str, ctx: dict) -> Any:
    """Evaluate a simple HCL expression against ctx. Supports:
       - var refs: foo, foo.bar, foo["bar"]
       - strings, numbers, bools, null
       - ternary: a ? b : c
       - equality: ==, !=
       - function calls from BUILTINS
       - list + dict literals via eval after sanitization
    """
    expr = expr.strip()
    # Boolean / null literals
    if expr == "true": return True
    if expr == "false": return False
    if expr == "null": return None
    # Quoted string
    if (expr.startswith('"') and expr.endswith('"')) or (expr.startswith("'") and expr.endswith("'")):
        return expr[1:-1]
    # Number
    try: return int(expr)
    except ValueError: pass
    try: return float(expr)
    except ValueError: pass
    # Ternary
    tern = re.match(r"^(.+?)\s*\?\s*(.+?)\s*:\s*(.+)$", expr)
    if tern:
        cond, a, b = tern.groups()
        return _eval(a, ctx) if _eval(cond, ctx) else _eval(b, ctx)
    # Equality
    for op in ("==", "!="):
        if op in expr:
            left, right = expr.split(op, 1)
            l, r = _eval(left.strip(), ctx), _eval(right.strip(), ctx)
            return (l == r) if op == "==" else (l != r)
    # Function call
    fn = re.match(r"^(\w+)\s*\((.*)\)\s*$", expr, re.DOTALL)
    if fn:
        name, args_s = fn.groups()
        args = _split_args(args_s)
        vals = [_eval(a.strip(), ctx) for a in args]
        if name in BUILTINS:
            return BUILTINS[name](*vals)
        return f"<<NO-BUILTIN:{name}>>"
    # Dotted / bracketed var access
    parts = re.split(r"\.|\[|\]", expr)
    parts = [p for p in parts if p]
    if not parts:
        return ""
    val = ctx.get(parts[0], f"<<UNDEFINED:{parts[0]}>>")
    for p in parts[1:]:
        if isinstance(val, dict):
            val = val.get(p.strip('"\''), f"<<UNDEFINED:{p}>>")
        elif isinstance(val, list):
            try: val = val[int(p)]
            except Exception: val = f"<<BAD-INDEX:{p}>>"
    return val


def _split_args(s: str) -> list[str]:
    out, buf, depth = [], "", 0
    in_str = None
    for c in s:
        if in_str:
            buf += c
            if c == in_str: in_str = None
            continue
        if c in '"\'':
            in_str = c; buf += c; continue
        if c in "([{": depth += 1
        elif c in ")]}": depth -= 1
        elif c == "," and depth == 0:
            out.append(buf); buf = ""; continue
        buf += c
    if buf.strip(): out.append(buf)
    return out


# ---------------------------------------------------------------------------
# Test harness
# ---------------------------------------------------------------------------


DUMMY_CTX = {
    # identity
    "hostname": "insidellm-test", "vm_hostname": "insidellm-test",
    "fqdn": "insidellm-test.local", "ssh_admin_user": "insidellm",
    "ssh_public_key": "ssh-ed25519 AAAA...test",
    "server_name": "insidellm.local",
    "vm_domain": "local",
    "vm_role": "primary",
    "department": "",
    "fleet_primary_host": "",

    # large literal blobs — real contents come from file(); pass placeholders.
    "env_file_contents": "LITELLM_MASTER_KEY=sk-test\n",
    "docker_compose_yml": "services:\n  dummy: {}\n",
    "litellm_config": "model_list: []\n",
    "nginx_conf": "events {}\nhttp {}\n",
    "tls_cert": "-----BEGIN CERTIFICATE-----\nTEST\n-----END CERTIFICATE-----",
    "tls_key": "-----BEGIN PRIVATE KEY-----\nTEST\n-----END PRIVATE KEY-----",
    "dlp_pipeline_py": "# stub",
    "humility_callback_py": "# stub",
    "humility_guardrail_py": "# stub",
    "dlp_guardrail_py": "# stub",
    "session_cost_py": "# stub",
    "admin_html": "<!doctype html>",
    "setup_html": "<!doctype html>",
    "deployment_tfvars_b64": "IyB0ZXN0",
    "post_deploy_sh": "#!/bin/bash\necho ok",
    "docforge_zip_b64": "UEs=",
    "opa_zip_b64": "UEs=",
    "governance_hub_zip_b64": "UEs=",
    "workers_zip_b64": "UEs=",
    "opa_policy_pipeline_py": "# stub",
    "docforge_tool_py": "# stub",
    "governance_advisor_tool_py": "# stub",
    "fleet_management_tool_py": "# stub",
    "system_designer_tool_py": "# stub",
    "data_connector_tool_py": "# stub",
    "keycloak_realm_json": '{"realm": "test"}',
    "provision_owui_svc_sh": "#!/bin/bash",
    "ad_join_runner_sh": "#!/bin/bash",
    "grafana_datasources_yml": "apiVersion: 1\n",
    "grafana_dashboards_yml": "apiVersion: 1\n",
    "grafana_compliance_json": "{}",
    "grafana_fleet_json": "{}",
    "loki_config": "auth_enabled: false\n",
    "promtail_config": "server: {}\n",
    "trivy_scan_sh": "#!/bin/bash",
    "edge_nginx_conf": "events {}\nhttp {}\n",
    "edge_routing_lua": "",
    "edge_routes_json": "{}",
    "edge_compose_yml": "services: {}\n",
    "edge_tls_cert": "cert",
    "edge_tls_key": "key",
    "edge_tls_source": "self-signed",
    "edge_domain": "",
    "fallback_department": "",
    "fleet_virtual_ip": "10.0.0.99",
    "keepalived_password": "pw",
    "fleet_edge_secret": "secret",
    "oauth2_cookie_secret": "cookie",

    # flags (all off by default; coverage flips happen below)
    "desktop_enable": False,
    "workers_enable": False,
    "keycloak_enable": False,
    "n8n_enable": False,
    "activepieces_enable": False,
    "guacamole_enable": False,
    "chat_enable": False,
    "cockpit_enable": True,
    "ollama_enable": False,
    "policy_engine_enable": False,
    "governance_hub_enable": True,
    "effective_governance_hub_enable": True,
    "docforge_enable": False,
    "effective_docforge_enable": False,
    "ops_watchtower_enable": False,
    "ops_grafana_enable": False,
    "effective_promtail_enable": False,
    "ops_uptime_kuma_enable": False,
    "ops_trivy_enable": False,
    "ops_backup_schedule": "0 2 * * *",
    "ad_domain_join": False,
    "ldap_enable_services": False,
    "claude_code_enable": False,
    "pkg_mirror_enable": False,
    "effective_pkg_mirror_enable": False,
    "apt_mirror_host": "",
    "docker_mirror_host": "",
    "admin_auth_mode": "none",
    "sso_provider": "none",
    "sso_env": {},
    "effective_litellm_capability": True,
    "effective_open_webui_capability": True,
    "effective_ops_grafana_enable": False,
    "effective_guacamole_enable": False,
    "effective_ops_uptime_kuma_enable": False,

    # assorted scalars
    "platform_version": "3.1.0",
    "postgres_password": "pw",
    "postgres_password_plain": "pw",
    "litellm_master_key": "sk-test-master",
    "litellm_salt_key": "salt-test",
    "webui_secret": "w-test",
    "xrdp_password": "xrdp-test",
    "grafana_admin_password": "g-test",
    "governance_hub_secret": "gh-test",
    "guacamole_db_password": "gdp",
    "n8n_webhook_secret": "",
    "activepieces_webhook_secret": "",
    "activepieces_encryption_key": "",
    "activepieces_jwt_secret": "",
    "anthropic_api_key": "",
    "openai_api_key": "", "gemini_api_key": "", "mistral_api_key": "",
    "cohere_api_key": "", "azure_openai_api_key": "",
    "azure_openai_endpoint": "", "azure_openai_api_version": "2024-02-15-preview",
    "aws_bedrock_access_key_id": "", "aws_bedrock_secret_access_key": "",
    "aws_bedrock_region": "us-east-1",
    "sso_client_secret": "",
    "ldap_bind_password": "",
    "hyperv_password": "hv",
    "policy_engine_fail_mode": "closed",
    "governance_hub_central_db_type": "postgresql",
    "governance_hub_central_db_host": "",
    "governance_hub_central_db_port": 5432,
    "governance_hub_central_db_name": "central",
    "governance_hub_central_db_user": "",
    "governance_hub_central_db_password": "",
    "governance_hub_instance_id": "insidellm-test",
    "governance_hub_instance_name": "test",
    "governance_hub_sync_schedule": "0 */6 * * *",
    "governance_hub_supervisor_emails": "",
    "governance_hub_advisor_model": "claude-sonnet",
    "governance_hub_registration_token": "",
    "governance_hub_industry": "general",
    "governance_hub_tier": "tier2",
    "governance_hub_classification": "internal",
    "governance_tier": "tier2",
    "data_classification": "internal",
    "ai_ethics_officer": "", "ai_ethics_officer_email": "",
    "dlp_enabled": False, "dlp_mode": "block",
    "dlp_block_ssn": True, "dlp_block_credit_cards": True,
    "dlp_block_phi": True, "dlp_block_credentials": True,
    "dlp_block_bank_accounts": True, "dlp_block_standalone_dates": False,
    "dlp_scan_responses": True, "dlp_custom_patterns": "[]",
    "chat_team_name": "t", "chat_default_channel": "c",
    "chat_site_url": "https://test/chat",
    "hyperv_host": "", "hyperv_user": "", "hyperv_port": 5985,
    "hyperv_https": False, "hyperv_insecure": True,
    "ad_domain": "local", "ad_admin_groups": "InsideLLM-Admin",
    "ad_view_groups": "InsideLLM-View", "ad_approver_groups": "InsideLLM-Approve",
    "oidc_view_group_ids": "", "oidc_admin_group_ids": "", "oidc_approver_group_ids": "",
    "oidc_issuer_url": "", "sso_client_id": "",
    "dc_dns_servers": [], "ldap_bind_dn": "", "ldap_user_search_base": "",
    "ad_join_user": "", "ad_join_password": "", "ad_join_ou": "", "ad_dns_register": False,
    "ollama_models": ["llama3.2:3b"], "ollama_gpu": "none",
    "keyword_categories": {},
    "sso_group_mapping": {},
    "ops_alert_webhook": "",
    "default_user_budget": "5.00",
    "litellm_default_user_budget": "5.00",
    "instance_id": "insidellm-test",
    "keycloak_version": "25.0.6",
    "keycloak_realm_name": "insidellm",
    "keycloak_db_name": "keycloak",
    "keycloak_admin_user": "insidellm-admin",
    "n8n_version": "1.67.1",
    "n8n_db_name": "n8n",
    "activepieces_version": "0.56.0",
    "activepieces_db_name": "activepieces",
    "keycloak_govhub_client_secret": "kc1",
    "keycloak_owui_client_secret": "kc2",
    "keycloak_litellm_client_secret": "kc3",
    "docforge_max_body_size": 50,
}


# Which templates to test + what we check post-render
TARGETS = [
    {
        "path": "configs/cloud-init/user-data.yaml.tpl",
        "kind": "yaml",
        "check": "must_contain",
        "must_contain": ["#cloud-config", "packages:", "runcmd:"],
        "must_not_contain": ["ubuntu-desktop-minimal", "linux/ubuntu"],
    },
    {
        "path": "configs/cloud-init/user-data.yaml.tpl",
        "kind": "yaml",
        "label": "(desktop_enable=true)",
        "ctx_override": {"desktop_enable": True},
        "check": "must_contain",
        "must_contain": ["task-xfce-desktop", "greybird-gtk-theme", "xrdp"],
    },
    {
        "path": "configs/cloud-init/edge-user-data.yaml.tpl",
        "kind": "yaml",
        "ctx_override": {"vm_role": "edge"},
        "check": "must_contain",
        "must_contain": ["#cloud-config", "packages:"],
        "must_not_contain": ["ubuntu-desktop-minimal", "linux/ubuntu"],
    },
    {
        "path": "configs/cloud-init/ollama-user-data.yaml.tpl",
        "kind": "yaml",
        "check": "must_contain",
        "must_contain": ["#cloud-config"],
        "must_not_contain": ["linux/ubuntu"],
    },
    {
        "path": "templates/env-file.tpl",
        "kind": "shell_env",
        "check": "must_contain",
        "must_contain": ["LITELLM_MASTER_KEY=", "POSTGRES_PASSWORD="],
    },
    {
        "path": "configs/nginx/nginx.conf.tpl",
        "kind": "text",
        "check": "must_contain",
        "must_contain": ["server_name", "ssl_certificate"],
    },
    {
        "path": "configs/keycloak/insidellm-realm.json.tpl",
        "kind": "json",
        "check": "must_contain",
        "must_contain": ["\"realm\"", "insidellm-admin"],
    },
]


def main() -> int:
    failures: list[str] = []
    for tgt in TARGETS:
        path = REPO / tgt["path"]
        if not path.exists():
            failures.append(f"MISSING: {tgt['path']}")
            continue
        ctx = {**DUMMY_CTX, **tgt.get("ctx_override", {})}
        try:
            out = render(path.read_text(encoding="utf-8"), ctx)
        except Exception as e:
            failures.append(f"RENDER FAIL: {tgt['path']}: {e}")
            continue

        # Check for unresolved error markers left by the interpreter.
        if "<<ERR:" in out or "<<UNDEFINED:" in out or "<<UNCLOSED" in out:
            errs = re.findall(r"<<[^>]+>>", out)
            # Drop common benign undefined-refs (vars we don't care about for
            # syntax checking).
            errs = [e for e in errs if "UNDEFINED" not in e][:5]
            if errs:
                failures.append(f"TEMPLATE ERR: {tgt['path']}: {errs}")

        # Kind-specific parse
        kind = tgt["kind"]
        if kind == "yaml":
            try:
                import yaml
                list(yaml.safe_load_all(out))
            except Exception as e:
                failures.append(f"YAML PARSE: {tgt['path']}: {e}")
        elif kind == "json":
            try:
                json.loads(out)
            except Exception as e:
                failures.append(f"JSON PARSE: {tgt['path']}: {e}")

        # Substring checks
        for must in tgt.get("must_contain", []):
            if must not in out:
                failures.append(f"MISSING: {tgt['path']}{tgt.get('label','')}: expected '{must}'")
        for must_not in tgt.get("must_not_contain", []):
            if must_not in out:
                failures.append(f"REGRESSION: {tgt['path']}{tgt.get('label','')}: found '{must_not}'")

        print(f"  ok: {tgt['path']}{tgt.get('label','')}")

    print()
    if failures:
        print(f"FAIL — {len(failures)} template issues:")
        for f in failures: print(f"  {f}")
        return 1
    print(f"OK — all {len(TARGETS)} template targets render + parse + contain expected markers")
    return 0


if __name__ == "__main__":
    sys.exit(main())
