# Inside LLM — Architecture & Product Use Case

**Version:** 3.1.0 | **Author:** Dan Medina, Uniformedi LLC | **Date:** April 2026
**Source:** [github.com/Uniformedi/InsideLLM](https://github.com/Uniformedi/InsideLLM) | **License:** [BSL 1.1](LICENSE) (converts to Apache 2.0 on April 11, 2030)

> **Ready to deploy?** Open the [Setup Wizard](html/Setup.html) for a guided, step-by-step configuration experience.
> Want to see the out-of-the-box defaults first? See [DefaultDeployment.html](html/DefaultDeployment.html) or the [markdown version](docs/DefaultDeployment.md) — all 129 Terraform variables with their default values.

### What's New in 3.1

- **Role-aware fleet modularity + edge router** -- single-switch deployment roles (primary/gateway/workstation/voice/edge). Department-based routing via OIDC claims. See [docs/FleetArchitecture.md](docs/FleetArchitecture.md).
- **Local package cache** -- primary VM auto-runs apt-cacher-ng + Docker registry pull-through. Peer VMs point at the primary and skip ~1.5 GB apt + ~4 GB Docker image traffic per deploy (~20 minutes saved). See [docs/LocalPackageCache.md](docs/LocalPackageCache.md).
- **Claude Code CLI on every VM** -- post-deploy installs Claude Code for the admin user on primary/gateway/workstation. Pre-seeds `/opt/InsideLLM/CLAUDE.md` with per-VM context so an SSH'd-in operator has an AI assistant scoped to that box out of the box. See [docs/ClaudeCode-On-VMs.md](docs/ClaudeCode-On-VMs.md).
- **Apache Guacamole (optional)** -- browser-based RDP/VNC/SSH gateway at `/remote/`. Enable with `guacamole_enable = true` in `terraform.tfvars`. Post-deploy seeds the `guacamole` Postgres DB, rotates the default `guacadmin` account, creates an `insidellm-admin` SYSTEM_ADMIN user (password = `LITELLM_MASTER_KEY`), and pre-populates RDP (port 3389) + SSH (port 22) connections for the local VM. When `ldap_enable_services = true`, the LDAP auth extension is installed automatically and AD users can log in with their `sAMAccountName`.
- **Platform Versioning** -- `VERSION` file at project root (currently `3.1.0`), wired through Terraform/Docker/Governance Hub. Admin topbar shows version badge. Fleet tracks per-node versions with outdated detection.
- **Unified SSO Across All Services** -- single IdP app registration (Azure AD or Okta) shared by Open WebUI, Grafana, LiteLLM, and the Admin Command Center. OIDC env vars auto-injected per service.
- **Active Directory Authentication** -- when domain-joined without a cloud IdP, the Admin Center uses LDAP bind against AD with group-based access control (`ad_admin_groups`). Uses `ldap3` pure Python library.
- **Admin Center Auth (3 modes)** -- OIDC (cloud SSO), LDAP (on-prem AD), or open (no auth). Determined automatically from deployment config. nginx `auth_request` delegates to Governance Hub JWT validation.
- **Color Theme Selector** -- 4 themes (Dark, Light, Midnight, High Contrast) with topbar picker, persisted in localStorage, no flash on load.
- **Specifications Tab** -- new admin tab listing all technical specifications the stack relies on (OpenAI v1, OpenAPI 3.0.3, OAuth 2.0, TLS 1.3, Docker Compose, etc.)
- **Fleet Database Setup Wizard** -- configure the central fleet database (MSSQL, MariaDB, PostgreSQL) from the admin UI with Test Connection and Save. MSSQL supports TrustServerCertificate and Encrypt options.
- **Fleet Node Versioning** -- each instance reports its platform version via sync. Fleet table shows version column with outdated badges. Migration SQL included.
- **Fleet Config Clone** -- "Clone Config" button on fleet nodes. Modal wizard to select snapshot, preview config sections, and download terraform.tfvars with the cloned configuration.
- **Monitoring Provisioning Script** -- `scripts/provision-monitoring.sh` idempotently configures Grafana (datasources, dashboards, alerts, Slack contact point), Uptime Kuma (10 monitors + Slack), and LiteLLM Slack alerting.
- **Setup Wizard Restructure** -- 9 steps (8 for WSL2) with dedicated "Optional Services" step grouping DocForge, Grafana, Uptime Kuma, and Governance Hub with their routes clearly labeled.
- **Grafana Provisioning Fix** -- moved datasource/dashboard YAML into required subdirectories, fixed dashboard JSON syntax errors and API format wrapping.
- **Admin Health Checks Fix** -- auto-detect host from `window.location.hostname`, use same-origin fetch instead of `no-cors`.
- **OpenAPI Docs Fix** -- Governance Hub API docs render correctly (downgraded spec from 3.1.0 to 3.0.3 for Swagger UI compatibility).

### What's New in 3.0

- **DocForge** -- Node.js file generation and conversion service (DOCX, XLSX, PPTX, PDF, CSV, ODF) with LibreOffice headless, accessible as an Open WebUI Tool
- **SSO Group-to-Team Mapping** -- Azure AD / Okta groups auto-map to LiteLLM teams with per-group budgets, rate limits, and model access
- **AI Governance Framework Compliance** -- governance tier classification, data classification, AI Ethics Officer tracking, configurable log retention
- **Industry Keyword Templates** -- 12 industry presets (Collections, Healthcare, Financial, Legal, Insurance, etc.) with curated regulatory keyword dictionaries
- **Keyword Analysis Engine** -- PostgreSQL full-text search on API requests with materialized views, topic distribution, and flagged request detection
- **Automated Operations Stack** -- Watchtower (container patching), Trivy (CVE scanning), Grafana+Loki (centralized logging), Uptime Kuma (health monitoring), PostgreSQL backup cron
- **Enterprise Governance Hub** -- FastAPI service for central repository sync (PostgreSQL/MariaDB/MSSQL), change management with supervisor approval, AI-powered governance advisor
- **Hash-Chained Audit Integrity** -- SHA-256 chain on all governance events (sync, proposals, approvals, snapshots) with verification endpoint
- **Fleet Management** -- cross-instance visibility, config snapshot restore, terraform.tfvars generation from any instance's snapshot
- **OPA Policy Engine** -- Open Policy Agent with Humility mandatory alignment + 6 industry policies (HIPAA, FDCPA, SOX, PCI-DSS, FERPA, GLBA), obligation execution pipeline
- **External Data Connectors** -- query PostgreSQL, MySQL, MSSQL, REST APIs with team-based RBAC, row filtering, field masking, and full audit logging
- **Interactive Admin Hub** -- command center SPA with governance dashboard, change management UI, fleet overview, and service status
- **AI System Designer** -- Open WebUI Tool that designs deployments, estimates costs, recommends configs, and plans multi-instance fleet architectures
- **PowerShell-native ISO creation** -- cloud-init ISO creation without WSL or Windows ADK using pure .NET (`scripts/New-CloudInitIso.ps1`)

### What Was New in 2.0

- **WSL2 deployment path** -- single PowerShell script, no Terraform or Hyper-V required (`scripts/Install-InsideLLM-WSL.ps1`)
- **Standalone initialization script** -- provision WSL2, Docker, SCFW, and TLS separately (`scripts/Initialize-InsideLLM.ps1`)
- **Supply Chain Firewall (SCFW)** -- Datadog's [supply-chain-firewall](https://github.com/DataDog/supply-chain-firewall) wraps `pip` to block known-malicious PyPI packages before installation
- **Local LLM support (Ollama)** -- run open-source models locally alongside Claude (Qwen 2.5 Coder 14B + Qwen 2.5 14B by default)
- **GPU acceleration** -- native GPU via WSL2, or GPU-PV/DDA passthrough for Hyper-V (`scripts/Setup-GPU-Passthrough.ps1`)
- **Setup Wizard** -- interactive HTML form that generates your config file (`html/Setup.html`)
- **Port forwarding script** -- expose all services to LAN clients (`scripts/Port-Forward-InsideLLM.ps1`)
- **Renamed from claude-wrapper to InsideLLM** -- all paths, services, and defaults updated
- **VM sizing updated** -- 8 vCPU / 32 GB RAM default (sized for Ollama), with guidance for lighter deployments
- **Correct Claude Code CLI env vars** -- `ANTHROPIC_AUTH_TOKEN` on port 4000

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Solution Overview](#2-solution-overview)
3. [Architecture Diagram](#3-architecture-diagram)
4. [Technology Stack](#4-technology-stack)
5. [Infrastructure Layer](#5-infrastructure-layer)
6. [Service Architecture](#6-service-architecture)
7. [Data Loss Prevention (DLP)](#7-data-loss-prevention-dlp)
7a. [Retrieval-Augmented Generation (RAG)](#7a-retrieval-augmented-generation-rag)
7b. [Local LLM Support (Ollama)](#7b-local-llm-support-ollama)
8. [Identity & Access Management](#8-identity--access-management)
9. [Security Architecture](#9-security-architecture)
10. [Cost Governance & Rate Limiting](#10-cost-governance--rate-limiting)
11. [Deployment & Operations](#11-deployment--operations)
11a. [WSL2 Deployment (Alternative)](#11a-wsl2-deployment-alternative)
12. [Product Use Case](#12-product-use-case)
13. [DocForge (File Generation & Conversion)](#13-docforge-file-generation--conversion)
14. [AI Governance & Compliance](#14-ai-governance--compliance)
15. [Enterprise Governance Hub](#15-enterprise-governance-hub)
16. [OPA Policy Engine](#16-opa-policy-engine)
17. [External Data Connectors](#17-external-data-connectors)
18. [Cloud-Init ISO Creation](#18-cloud-init-iso-creation)

---

## 1. Executive Summary

The Inside LLM is a **self-hosted, on-premises AI gateway** that provides
enterprise-grade access to Anthropic's Claude models. A single `terraform apply` (or a PowerShell script for WSL2)
deploys a fully configured Ubuntu VM on Windows Hyper-V, running five containerized
services that deliver:

- **Chat interface** for non-technical users (Open WebUI)
- **API gateway** for developers and CLI tools (LiteLLM)
- **Data Loss Prevention** scanning on every message and uploaded file (custom pipeline)
- **Document Q&A (RAG)** with local embeddings — upload files and ask questions against them
- **SSO integration** with Azure AD or Okta (OIDC)
- **Per-user budgets and rate limits** with real-time enforcement
- **Real-time monitoring** of containers, host resources, and database metrics (Netdata)
- **Admin portal** — interactive command center with governance dashboard, change management UI, fleet overview, specifications reference, 4 color themes, and version tracking (`/admin`)
- **Full audit trail** of every API call with hash-chained integrity verification
- **File generation** — create DOCX, XLSX, PPTX, PDF from chat via DocForge
- **AI governance compliance** — industry keyword analysis, OPA policy enforcement, Humility alignment
- **Enterprise fleet management** — central repository sync, cross-instance restore, multi-DB support (PostgreSQL/MariaDB/MSSQL)
- **Automated operations** — container patching (Watchtower), CVE scanning (Trivy), centralized logging (Grafana+Loki), health monitoring (Uptime Kuma)
- **External data connectors** — query external databases and APIs with team-based RBAC and audit logging

All traffic to Anthropic's API is brokered through this internal stack. The
organization retains complete control over who accesses Claude, what data they
send, and how much they spend.

```
+------------------------------------------------------------------+
|                     ENTERPRISE BOUNDARY                          |
|                                                                  |
|   Users  ──────>  [ Inside LLM ]  ──────>  Anthropic   |
|                    DLP | Auth | Budgets                API       |
|                    Audit | Rate Limits                           |
+------------------------------------------------------------------+
```

---

## 2. Solution Overview

### The Problem

Organizations adopting AI face three critical challenges:

1. **Data Leakage** — Employees paste sensitive data (SSNs, PHI, credentials)
   into AI chat interfaces with no guardrails
2. **Cost Control** — Unmanaged API usage can generate thousands of dollars
   in charges within hours
3. **Compliance** — No audit trail of what data was sent to AI services,
   making regulatory compliance impossible

### The Solution

The Inside LLM sits between users and the Anthropic API, acting as an
**intelligent proxy** that enforces DLP policies, authenticates users via
corporate identity providers, enforces per-user spend limits, and logs every
interaction — all without modifying the Claude API experience.

```
 BEFORE (Direct Access)              AFTER (Inside LLM)
 ========================            ============================

 Employee ──> Anthropic API          Employee ──> [DLP + Auth + Budget] ──> Anthropic API
                                                        |
 - No DLP scanning                          - PII/PHI blocked in messages AND files
 - No per-user budgets                      - Per-user daily spend caps
 - No audit trail                           - Full audit trail (Langfuse)
 - No SSO integration                       - Azure AD / Okta SSO
 - No document Q&A                          - RAG with local embeddings (no data leaves network)
 - Shared API key                           - Individual user keys
```

---

## 3. Architecture Diagram

### High-Level Architecture

```
                         +----------------------------------------------+
                         |          Windows Hyper-V / WSL2 Host         |
                         |          (Windows 11 Pro / Server)            |
                         |                                              |
                         |  +----------------------------------------+  |
                         |  |         Debian 12 (Bookworm)           |  |
                         |  |         SCFW (pip wrapper)              |  |
                         |  |                                         |  |
+----------+ HTTPS 443   |  |  +-----------------------------------+  |  |
|          |-------------+--+->|          Nginx 1.27                |  |  |
|  Users   |             |  |  |   TLS 1.2/1.3 Termination         |  |  |
| (Browser)|             |  |  |   HSTS | Security Headers         |  |  |
+----------+             |  |  +--+-------+-------+--------+----+--+  |  |
                         |  |     |       |       |        |    |     |  |
+----------+ HTTPS 443   |  |  /  | /v1/  |/litellm/ /netdata/ /admin |  |
|  Claude  |-------------+--+->   |       |       |        |    |     |  |
|  Code    |             |  |     v       v       v        v    v     |  |
|  CLI     |             |  |  +------+ +------+ +--------+ +------+ |  |
+----------+             |  |  | Open | | Lite | | Netdata| | Admin| |  |
                         |  |  | Web  | | LLM  | | Monitor| | Portal |  |
                         |  |  | UI   | | Proxy|<-+:19999 | | (HTML) |  |
                         |  |  |:8080 | |:4000 |  +--------+ +------+ |  |
                         |  |  +--+---+ +--+---+  |                  |  |
                         |  |     |        |       |                  |  |
                         |  |  DLP Pipe  Budget/   |                  |  |
                         |  |  (in/out)  Rate Lim  |                  |  |
                         |  |     |        |       |                  |  |
                         |  |     +---+----+       |                  |  |
                         |  |         |            |                  |  |
                         |  |         v            |                  |  |
                         |  |  +----------+ +-----+----+             |  |
                         |  |  |PostgreSQL| | Redis    |---+         |  |
                         |  |  |16-alpine | | 7-alpine |   |         |  |
                         |  |  |Users,    | | Rate     |   |         |  |
                         |  |  |Spend,    | | Limits,  |   |         |  |
                         |  |  |Audit     | | Budget   |   |         |  |
                         |  |  +----------+ +----------+   |         |  |
                         |  +----------------------------------------+  |
                         +----------------------------------------------+
                                         |
                                         | HTTPS (api.anthropic.com)
                                         v
                                  +---------------+
                                  |  Anthropic    |
                                  |  Claude API   |
                                  | Sonnet|Haiku  |
                                  | Opus          |
                                  +---------------+
```

### Container Network Topology

```
Docker Bridge Network: insidellm-internal (172.28.0.0/16)
======================================================

+--------------+     +--------------+
| PostgreSQL   |     | Redis        |
| :5432        |     | :6379        |
| (internal)   |     | (internal)   |
+------+-------+     +------+-------+
       |                     |
       +---------+-----------+
                 |
          +------+-------+
          |   LiteLLM    |----------->  api.anthropic.com
          |   :4000      |
          +------+-------+
                 |
          +------+-------+         +--------------+
          | Open WebUI   |         | Netdata      |
          | :8080        |         | :19999       |
          +------+-------+         | (monitoring) |
                 |                 +------+-------+
          +------+-------+               |
          |   Nginx      |---------------+
          |  :80  :443   |  <--------  External Users
          +--------------+
               |
          +----+------+
          | pgAdmin   |
          | :5050     |
          +-----------+

All traffic routed through Nginx (TLS):
  /           -> Open WebUI  (:8080)
  /v1/        -> LiteLLM     (:4000)
  /litellm/   -> LiteLLM     (:4000)
  /netdata/   -> Netdata     (:19999)
  /admin      -> Admin Portal (static HTML)

Exposed Host Ports:
  80   -> Nginx   (HTTP redirect to HTTPS)
  443  -> Nginx   (HTTPS -- primary entry point)
  4000 -> LiteLLM (direct API access)
  5050 -> pgAdmin (database admin)
```

### Request Flow

```
  User types message in Open WebUI
           |
           v
  +------------------+
  | Nginx            |  HTTPS termination, add security headers
  | (reverse proxy)  |
  +--------+---------+
           |
           v
  +------------------+
  | LiteLLM Proxy    |  1. DLP INLET: Scan message + inlined files
  | (DLP Gateway)    |     - Excel, CSV, PDF, Word, PPTX scanned
  |                  |     - SSN? BLOCK
  |                  |     - Credit card? BLOCK
  |                  |     - PHI? BLOCK
  |                  |     - API keys? BLOCK
  |                  |     - Custom patterns? BLOCK
  |                  |  2. Authenticate user (SSO token / API key)
  |                  |  3. Check budget (PostgreSQL: $5/day remaining?)
  |                  |  4. Check rate limit (Redis: 30 RPM / 100K TPM?)
  |                  |  5. Route to correct Claude model
  +--------+---------+
           | Message + clean files pass DLP
           v
  +------------------+
  | Anthropic API    |  Claude generates response
  +--------+---------+
           |
           v
  +------------------+
  | LiteLLM Proxy    |  6. DLP OUTLET: Scan assistant response
  | (DLP Gateway)    |     - Redact any echoed-back PII/PHI/creds
  |                  |  7. Record token usage + cost in PostgreSQL
  |                  |  8. Log to Langfuse (audit trail)
  |                  |  9. Update Redis rate limit counters
  +--------+---------+
           |
           v
  User sees the response
```

---

## 4. Technology Stack

All components are **free and open-source software (FOSS)**:

| Component | Project | License | Version | Purpose |
|-----------|---------|---------|---------|---------|
| **API Gateway** | [LiteLLM](https://github.com/BerriAI/litellm) | MIT | latest | Authentication, model routing, budgets, rate limiting, audit |
| **Chat Interface** | [Open WebUI](https://github.com/open-webui/open-webui) | MIT | latest | Browser-based chat UI, RAG, document upload, pipeline host |
| **Local LLM** | [Ollama](https://ollama.com/) | MIT | latest | Local model inference (Qwen 2.5 Coder, Qwen 2.5, etc.) |
| **Reverse Proxy** | [Nginx](https://nginx.org/) | BSD-2 | 1.27 | TLS termination, HTTPS routing, security headers |
| **Database** | [PostgreSQL](https://www.postgresql.org/) | PostgreSQL | 16 | User data, spend tracking, team budgets, audit logs |
| **Cache** | [Redis](https://redis.io/) | BSD-3 | 7 | Rate limit counters, budget enforcement, LiteLLM internal state |
| **Monitoring** | [Netdata](https://www.netdata.cloud/) | GPL-3 | stable | Real-time monitoring of containers, host, PostgreSQL, Redis |
| **Supply Chain** | [SCFW](https://github.com/DataDog/supply-chain-firewall) | Apache 2.0 | latest | Blocks malicious PyPI packages before pip install |
| **Containers** | [Docker](https://www.docker.com/) + [Compose](https://docs.docker.com/compose/) | Apache 2.0 | CE | Container orchestration, networking, health checks |
| **IaC** | [Terraform](https://www.terraform.io/) | BSL 1.1 | >= 1.5 | Infrastructure provisioning, config templating (Hyper-V path) |
| **Provisioning** | [cloud-init](https://cloudinit.readthedocs.io/) | Apache 2.0 | default | First-boot VM automation (Hyper-V path) |
| **Hypervisor** | [Hyper-V](https://learn.microsoft.com/en-us/virtualization/hyper-v-on-windows/) | Windows | Win 11 Pro | VM hosting (Hyper-V path) |
| **WSL2** | [Windows Subsystem for Linux](https://learn.microsoft.com/en-us/windows/wsl/) | Windows | Win 11 22H2+ | Lightweight Linux runtime (WSL2 path, native GPU support) |
| **Audit** | [Langfuse](https://langfuse.com/) | MIT | callback | LLM observability, prompt logging, cost tracking |
| **Guest OS** | [Ubuntu](https://ubuntu.com/) | FOSS | 24.04 LTS | Server operating system (both paths) |

### Why These Technologies?

```
+------------------------------------------------------------------+
| Selection Criteria                                               |
+------------------------------------------------------------------+
|                                                                  |
| LiteLLM      - Only FOSS proxy with per-user budgets + SSO      |
|              - OpenAI-compatible API (works with Claude Code)    |
|              - Built-in admin UI for non-technical admins        |
|                                                                  |
| Open WebUI   - ChatGPT-like UX (zero learning curve)            |
|              - Pipeline system enables custom DLP filters        |
|              - RAG built-in (document Q&A out of the box)        |
|                                                                  |
| PostgreSQL   - Enterprise-proven, ACID-compliant                 |
|              - Perfect for financial data (spend tracking)       |
|                                                                  |
| Redis        - Sub-millisecond rate limit enforcement            |
|              - Budget tracking and LiteLLM operational state     |
|                                                                  |
| Nginx        - Industry standard for TLS termination             |
|              - WebSocket support (streaming responses)           |
|                                                                  |
| Ollama       - Run open-source LLMs locally (no API costs)       |
|              - Qwen 2.5 models for coding and general use        |
|              - Native GPU acceleration via WSL2 or Hyper-V DDA   |
|                                                                  |
| Hyper-V      - Built into Windows Pro/Enterprise (no cost)       |
|              - IT departments already have Hyper-V expertise     |
|                                                                  |
| WSL2         - Zero-config deployment (one PowerShell script)    |
|              - Native GPU passthrough (no DDA setup needed)      |
|              - Ideal for developers and evaluation               |
+------------------------------------------------------------------+
```

---

## 5. Infrastructure Layer

### Deployment Target

The stack deploys to a single VM on a Windows Hyper-V host. This is ideal for
organizations that want AI capabilities without cloud dependencies.

```
+--------------------------------------------------+
| Windows 11 Pro / Server 2022+                    |
| (Hyper-V enabled)                                |
|                                                  |
|  Terraform (local exec)                          |
|      |                                           |
|      | WinRM (NTLM, port 5985)                   |
|      v                                           |
|  Hyper-V Manager                                 |
|      |                                           |
|      | Creates VM + attaches cloud-init ISO       |
|      v                                           |
|  +--------------------------------------------+  |
|  | Debian 12 (Bookworm) VM                    |  |
|  |   - Gen 2 (UEFI + Secure Boot)            |  |
|  |   - 8 vCPU, 32 GB RAM, 80 GB disk         |  |
|  |   - Internal switch + NAT (isolated)       |  |
|  |   - SSH key-only access                    |  |
|  +--------------------------------------------+  |
+--------------------------------------------------+
```

### Networking Models

| Mode | Description | Use Case |
|------|-------------|----------|
| **Internal + NAT** (default) | VM on isolated virtual switch (`192.168.100.0/24`), NAT for internet | Single-host deployments, maximum isolation |
| **External** | VM bridged to physical NIC, gets LAN IP | Multi-host access, existing network infrastructure |

### VM Provisioning Pipeline

```
 terraform apply
       |
       v
 1. Generate secrets (random_password)
 2. Generate TLS cert (tls_self_signed_cert) -- or use BYOC
 3. Render all templates (docker-compose, nginx, litellm, cloud-init)
 4. Create Hyper-V VM (hyperv_machine_instance)
 5. Resize boot VHDX to 80 GB
 6. Build cloud-init ISO (genisoimage via WSL)
 7. Attach ISO + boot VM
 8. Wait for cloud-init completion (SSH poll, up to 10 min)
 9. Verify services are healthy
       |
       v
 All 5 containers running. Stack operational.
```

---

## 6. Service Architecture

### PostgreSQL 16

**Role:** Persistent state store for LiteLLM.

| Data Stored | Purpose |
|-------------|---------|
| User records | Who has accessed the system |
| API keys | Per-user and per-team authentication tokens |
| Spend tracking | Token usage and dollar amounts per user per day |
| Team budgets | Organizational budget allocations |
| Team membership | User-to-team assignments |
| Audit logs | Historical record of API calls |

- **Volume:** `/opt/InsideLLM/data/postgres` (persistent across restarts)
- **Health check:** `pg_isready -U litellm` every 10s
- **Not exposed** to host network -- internal access only

### Redis 7

**Role:** Operational store for LiteLLM's rate limiting, budget enforcement, and internal state. Redis does **not** cache LLM responses -- every request still goes to Anthropic's API (or Ollama for local models).

| Data Stored | Purpose |
|-------------|---------|
| Rate limit counters | Per-user RPM (30) and TPM (100K) enforcement |
| Budget tracking | Real-time spend against per-user daily limits and global monthly cap |
| Routing/session state | LiteLLM internal state for fast lookups during request processing |

- **Memory:** Capped at 256 MB with `allkeys-lru` eviction (least-recently-used keys are evicted when the cap is hit, which works well for ephemeral rate limit counters)
- **Volume:** `/opt/InsideLLM/data/redis` (persistence across restarts)
- **Health check:** `redis-cli ping` every 10s

### LiteLLM Proxy

**Role:** Central API gateway -- the brain of the stack.

```
+--------------------------------------------------------------+
|                       LiteLLM Proxy                          |
+--------------------------------------------------------------+
|                                                              |
|  Authentication                                              |
|  +------------------+  +------------------+                  |
|  | Master Key       |  | Per-User API Keys|                  |
|  | (admin access)   |  | (team-scoped)    |                  |
|  +------------------+  +------------------+                  |
|  +------------------+  +------------------+                  |
|  | Azure AD SSO     |  | Okta SSO         |                  |
|  | (OIDC)           |  | (OIDC)           |                  |
|  +------------------+  +------------------+                  |
|                                                              |
|  Model Routing                                               |
|  +------------------+  +------------------+  +-----------+   |
|  | claude-sonnet    |  | claude-haiku     |  | claude-   |   |
|  | (4.5)            |  | (4.5)            |  | opus(4.6) |   |
|  +------------------+  +------------------+  +-----------+   |
|                                                              |
|  Governance                                                  |
|  +------------------+  +------------------+  +-----------+   |
|  | Per-user budgets |  | Rate limiting    |  | Global    |   |
|  | $5/day default   |  | 30 RPM/100K TPM  |  | $100/mo   |   |
|  +------------------+  +------------------+  +-----------+   |
|                                                              |
|  Observability                                               |
|  +------------------+  +------------------+                  |
|  | Langfuse audit   |  | Admin dashboard  |                  |
|  | (every API call) |  | (spend, usage)   |                  |
|  +------------------+  +------------------+                  |
+--------------------------------------------------------------+
```

**Available Claude Models:**

| Model Alias | Backend | Default |
|-------------|---------|---------|
| `claude-sonnet` | `anthropic/claude-sonnet-4-5-20250929` | Always on |
| `claude-haiku` | `anthropic/claude-haiku-4-5-20251001` | Enabled |
| `claude-opus` | `anthropic/claude-opus-4-6` | Enabled |

Anthropic prompt caching is handled automatically by LiteLLM when applicable.

### Open WebUI

**Role:** User-facing chat interface with pipeline extensibility.

- **ChatGPT-like interface** -- zero learning curve for end users
- **RAG + Tools integration** -- document Q&A with local embeddings, and admin UI for custom tools
- **RAG (Retrieval-Augmented Generation)** -- users upload documents and ask
  questions against them using local `sentence-transformers/all-MiniLM-L6-v2`
  embeddings (no external API needed). Full-context mode injects entire file
  contents into the prompt for maximum accuracy.
- **User management** -- self-registration with role-based access
- **Community sharing disabled** -- no data leaves the organization

### Nginx 1.27

**Role:** Secure entry point, TLS termination, request routing.

```
Port 80 (HTTP)                   Port 443 (HTTPS)
+------------------+             +-----------------------------------+
| /health -> 200   |             | /          -> Open WebUI (:8080)  |
| /*      -> 301   |--redirect-->| /litellm/  -> LiteLLM UI (:4000) |
|   to HTTPS       |             | /v1/       -> LiteLLM API (:4000)|
+------------------+             | /netdata/  -> Netdata    (:19999)|
                                 | /admin     -> Admin Portal (HTML) |
                                 | /nginx-health -> 200 OK          |
                                 +-----------------------------------+
```

**TLS Configuration:**
- Protocols: TLS 1.2 and TLS 1.3 only
- Cipher suite: `HIGH:!aNULL:!MD5`
- HSTS: 1 year with subdomains
- HTTP/2 enabled
- Self-signed cert auto-generated (or BYOC)

---

## 7. Data Loss Prevention (DLP)

### Overview

The DLP system is implemented as a **LiteLLM gateway callback** (`dlp_guardrail.py`) that
scans all traffic at the API gateway level. It intercepts every message and uploaded file at two critical
points in the conversation flow, covering **all clients** (Open WebUI, Claude Code CLI, direct API consumers). It is the primary compliance control in the stack.

```
+=============================================================+
|                     DLP Pipeline Flow                        |
+=============================================================+
|                                                             |
|  USER MESSAGE + UPLOADED FILES                              |
|      |                                                      |
|      v                                                      |
|  +-------------------------------------------------------+  |
|  |              INLET (Pre-Processing)                    |  |
|  |                                                        |  |
|  |  1. Scan message text:                                 |  |
|  |     - Extract text (plain or multimodal)               |  |
|  |     - Run ALL active regex patterns                    |  |
|  |                                                        |  |
|  |  2. Scan uploaded files:                               |  |
|  |     - Read file from disk (before RAG sees it)         |  |
|  |     - Extract text per format:                         |  |
|  |       Excel (.xlsx/.xls) | CSV/TSV | PDF               |  |
|  |       Word (.docx) | PowerPoint (.pptx)                |  |
|  |       Plain text (.txt, .md, .json, .xml, etc.)        |  |
|  |     - Run ALL active regex patterns on content         |  |
|  |                                                        |  |
|  |  3. If match found:                                    |  |
|  |     - BLOCK mode: Reject with error message            |  |
|  |     - REDACT mode: Strip flagged files, redact text    |  |
|  |  4. Log detection (without sensitive data)             |  |
|  +-------------------------------------------------------+  |
|      |                                                      |
|      | Clean message + clean files only                     |
|      v                                                      |
|  [ RAG --> LiteLLM --> Anthropic API --> Claude ]            |
|      |                                                      |
|      | Claude's response                                    |
|      v                                                      |
|  +-------------------------------------------------------+  |
|  |             OUTLET (Post-Processing)                   |  |
|  |                                                        |  |
|  |  For each assistant message:                           |  |
|  |    1. Scan response text (incl. RAG excerpts)          |  |
|  |    2. If sensitive data echoed back:                   |  |
|  |       - Always REDACT (never show to user)             |  |
|  |    3. Log detection                                    |  |
|  +-------------------------------------------------------+  |
|      |                                                      |
|      v                                                      |
|  SANITIZED RESPONSE shown to user                           |
+=============================================================+
```

### File Upload Scanning

Open WebUI extracts text from uploaded files and inlines it into the messages array before
the request leaves the frontend. The DLP gateway callback scans both the inlined file content
and user messages before they reach Anthropic. If sensitive data is detected, the request is
blocked or redacted before the LLM ever sees it.

```
Supported File Formats:
+-------------+--------------+--------------------------------+
| Format      | Library      | What Gets Scanned              |
+-------------+--------------+--------------------------------+
| .xlsx/.xlsm | openpyxl     | All cells from all sheets      |
| .xls        | xlrd         | All cells from all sheets      |
| .csv/.tsv   | stdlib csv   | All rows and columns           |
| .pdf        | pypdf        | Text from all pages            |
| .docx       | docx2txt     | All paragraphs                 |
| .pptx       | python-pptx  | Text from all slides           |
| .txt .md    | plain read   | Full file content              |
| .json .xml  |              |                                |
| .py .js     |              |                                |
| .yaml .sql  |              |                                |
+-------------+--------------+--------------------------------+
| Files > 50 MB (configurable) are skipped for performance   |
| Unsupported formats are logged and skipped (never blocked) |
+------------------------------------------------------------+
```

In **block mode**, the error message identifies which files contain what types
of sensitive data:

```
 DLP Filter Blocked This Message

 Uploaded files contain sensitive information:
   - employees.xlsx: Social Security Number, Credit Card Number
   - patient_notes.pdf: Medical Record Number, Date of Birth

 Please remove the sensitive data and try again.
```

In **redact mode**, flagged files are stripped from the request (never sent to
RAG or the LLM), and a system message notifies the user which files were removed.

### Operating Modes

```
 BLOCK MODE (Default)                    REDACT MODE
 ================================        ================================

 User: "My SSN is 123-45-6789"          User: "My SSN is 123-45-6789"
        |                                        |
        v                                        v
 +------------------+                    +------------------+
 | DLP BLOCKS       |                    | DLP REDACTS      |
 | MESSAGE          |                    | MESSAGE          |
 +------------------+                    +------------------+
        |                                        |
        v                                        v
 "Your message contains data             Sent to Claude as:
  that appears to be sensitive            "My SSN is [REDACTED-SSN]"
  information (Social Security                    |
  Number). This message has                       v
  been blocked."                          Claude responds normally
                                          (never sees real SSN)
 Message NEVER reaches Claude.
```

### Detection Categories

#### Personally Identifiable Information (PII)

| Pattern | What It Detects | Severity |
|---------|----------------|----------|
| SSN | `123-45-6789`, `123 45 6789`, `123456789` (incl. Unicode dashes) | Critical |
| SSN (labeled) | `SSN: 123456789`, `Social Security: 123-45-6789` | Critical |
| Credit Card (branded) | Visa (4xxx), MC (5[1-5]xx), Amex (3[47]xx), Discover (6011/65xx) | Critical |
| Credit Card (generic) | Any `xxxx-xxxx-xxxx-xxxx` pattern | High |
| Bank Routing | Routing/ABA numbers (9 digits) | Critical |
| Bank Account | Account numbers (8-17 digits) | Critical |

#### Protected Health Information (PHI / HIPAA)

| Pattern | What It Detects | Severity |
|---------|----------------|----------|
| Medical Record # | MRN, Medical Record, Patient ID + digits | Critical |
| Date of Birth (labeled) | DOB, Date of Birth, birthday, birthdate, born on, D.O.B., fecha de nacimiento + date | High |
| Date of Birth (ISO) | `YYYY-MM-DD` standalone dates (e.g., `1955-11-09`) | Medium |
| Date of Birth (text month) | Dates with text months (e.g., `November 9, 1955`, `9 Nov 1955`) | Medium |
| Date of Birth (standalone) | `MM/DD/YYYY` and `DD/MM/YYYY` standalone dates | Medium |
| Diagnosis Codes | ICD-9 and ICD-10-CM/PCS codes | Medium |

#### Credentials & Secrets

| Pattern | What It Detects | Severity |
|---------|----------------|----------|
| API Keys | `sk-xxxx...`, `api_key=xxxx` | Critical |
| Passwords | `password=`, `passwd=`, `pwd=` + value | Critical |
| Connection Strings | `Server=...;Password=...` | Critical |
| AWS Keys | `AKIA`/`ASIA` prefix + 16 characters | Critical |
| Private Keys | `-----BEGIN PRIVATE KEY-----` | Critical |

#### Custom Patterns (organization-defined)

Administrators can add arbitrary regex patterns via Terraform variables or
the Open WebUI admin panel at runtime -- no redeployment needed.

### DLP Configuration

DLP is configured via **Terraform variables (deploy-time)**, which are passed to the LiteLLM
gateway callback on container startup:

```hcl
# terraform.tfvars
dlp_enable             = true
dlp_block_ssn          = true
dlp_block_credit_cards = true
dlp_block_phi          = true
dlp_block_credentials  = true
dlp_custom_patterns    = {
  "client_account" = "\\bACCT[#-]?\\d{8,}\\b"
  "internal_id"    = "\\bUID-[A-Z]{2}\\d{6}\\b"
}
```

For runtime configuration changes, administrators can use **Governance Hub** to create
`settings_overrides` entries that adjust DLP behavior without redeployment. Runtime-only
settings (per the table below) are managed via Governance Hub:

Alternatively, for the legacy Open WebUI pipeline (if enabled as an optional frontend pre-filter),
navigate to **Admin > Pipelines > DLP Filter > Valves**:

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `true` | Master on/off |
| `mode` | `block` | `block` or `redact` |
| `block_ssn` | `true` | SSN detection |
| `block_credit_cards` | `true` | Credit card detection |
| `block_phi` | `true` | PHI detection |
| `block_credentials` | `true` | Secret detection |
| `block_bank_accounts` | `true` | Bank info detection **(runtime only)** |
| `block_standalone_dates` | `true` | Detect standalone date patterns (MM/DD/YYYY, YYYY-MM-DD) **(runtime only)** |
| `scan_file_uploads` | `true` | Scan uploaded files (Excel, PDF, etc.) **(runtime only)** |
| `max_file_size_mb` | `50` | Max file size to scan (larger files skipped) **(runtime only)** |
| `log_detections` | `true` | Audit logging **(runtime only)** |
| `custom_patterns` | `{}` | JSON regex map |

### DLP Audit Logging

Detections are logged **without the actual sensitive data**, creating an
audit trail that is itself compliant:

```
 Log entry example:
 WARNING - DLP: Detected sensitive data from user=john.doe:
           Social Security Number (critical), API Key (critical)

 What IS logged:     Pattern name, severity, user ID, timestamp
 What is NOT logged: The actual sensitive values
```

### Multimodal Content Handling

The DLP pipeline handles plain text, multimodal (text + image) messages, and
uploaded files. For multimodal content, it extracts all text portions and scans
them. For files, it reads them directly from disk before RAG processes them,
extracting text using format-specific parsers (openpyxl for Excel, pypdf for
PDF, docx2txt for Word, python-pptx for PowerPoint, stdlib csv for CSV/TSV,
and plain reads for text-based formats).

### Deployment

The DLP gateway callback is configured at LiteLLM container startup via `config.yaml.tpl`,
which is rendered from `dlp_*` Terraform variables. No manual registration is needed --
`terraform apply` handles everything:

1. `terraform apply` renders `config.yaml.tpl` with DLP settings
2. LiteLLM container starts and loads the callback class
3. All inbound/outbound traffic is scanned immediately
4. Configuration changes require container restart

The legacy Open WebUI pipeline (if enabled as an optional frontend filter) is registered
as an Open WebUI Function during post-deployment; it is registered **inactive** by default
and can be manually activated via **Admin > Functions** if desired.

---

## 7a. Retrieval-Augmented Generation (RAG)

### Overview

Open WebUI includes built-in RAG capabilities that allow users to upload documents
and ask questions about their contents. Claude receives the full file context
alongside the user's message, enabling accurate document-based Q&A.

```
  User uploads file (Excel, CSV, PDF, Word, etc.)
       |
       v
  +----------------------------+
  | Open WebUI File Handler    |
  |  1. Extract text content   |
  |  2. Chunk and embed with   |
  |     sentence-transformers  |
  |  3. Store in ChromaDB      |
  +----------------------------+
       |
       v
  User asks a question
       |
       v
  +----------------------------+
  | DLP Pipeline (inlet)       |  <-- Scans message + file for PII
  +----------------------------+
       |
       v
  +----------------------------+
  | RAG Context Injection      |
  |  Full-context mode:        |
  |  Entire file content is    |
  |  injected into the prompt  |
  +----------------------------+
       |
       v
  +----------------------------+
  | LiteLLM -> Claude API      |  Claude sees file content + question
  +----------------------------+
```

### Configuration

| Setting | Value | Description |
|---------|-------|-------------|
| `RAG_EMBEDDING_ENGINE` | *(empty)* | Uses local sentence-transformers (no external API) |
| `RAG_EMBEDDING_MODEL` | `sentence-transformers/all-MiniLM-L6-v2` | Lightweight, fast embedding model |
| `RAG_FULL_CONTEXT` | `true` | Injects entire file content (not just similar chunks) |
| `CHUNK_SIZE` | `1500` | Characters per chunk for vector storage |
| `CHUNK_OVERLAP` | `100` | Overlap between chunks |

### Why Local Embeddings?

The stack uses **local sentence-transformers** instead of OpenAI's embedding API:

- **No additional API key required** -- works with only the Anthropic API key
- **No data leaves the network** -- embeddings are computed inside the container
- **No per-token cost** -- embedding operations are free
- **Consistent with the on-premises design philosophy** -- all processing stays local

### DLP + RAG Integration

The DLP gateway and RAG system work together in sequence:

1. **Open WebUI RAG extracts text** -- uploaded files are processed by the RAG engine and their text content is inlined into the messages array
2. **DLP scans inlined content** -- the LiteLLM gateway callback scans the inlined file text and user messages for sensitive data
3. **Full context injection** -- Claude receives the complete file content alongside the user's question (only if it passes DLP)
4. **DLP scans the response** -- the outlet filter checks Claude's response for any echoed-back PII

If a file contains sensitive data (SSNs, credit cards, PHI), the DLP gateway callback blocks the
entire request before Claude ever sees the file contents.

---

## 7b. Local LLM Support (Ollama)

InsideLLM can optionally run local open-source models alongside the Anthropic API
using [Ollama](https://ollama.com). This keeps all inference on-premises with no
external API calls for the local models.

### Enabled by Default

Ollama is enabled by default with two models (`qwen2.5-coder:14b` and `qwen2.5:14b`).
The VM defaults (8 vCPU, 32 GB RAM) are sized accordingly.

To customize the models, set `ollama_models` in your `terraform.tfvars`:

```hcl
ollama_models = ["qwen2.5-coder:14b", "llama3.1:8b", "qwen2.5:14b"]
```

### Disabling Ollama (lighter deployment)

If you only need the Anthropic API models and want a smaller VM footprint:

```hcl
# Disable Ollama
ollama_enable = false

# Reduce VM resources
vm_processor_count      = 4
vm_memory_startup_bytes = 8589934592    # 8 GB (down from 32 GB)
```

This cuts the VM memory requirement from 32 GB to 8 GB and halves the CPU allocation.

### How It Works

When enabled, Terraform adds two containers to the stack:

| Container | Purpose |
|-----------|---------|
| `insidellm-ollama` | Ollama inference server (port 11434) |
| `insidellm-ollama-pull` | One-shot sidecar that pulls the configured models on first boot |

LiteLLM automatically gets routes for each model (e.g., `ollama/qwen2.5-coder:14b`),
so they appear in the Open WebUI model dropdown and are accessible via the API.

### Architecture

```
Users --> Open WebUI --> LiteLLM --> Anthropic API (Claude models)
                                \-> Ollama :11434  (local models)
```

All containers share the `insidellm-internal` Docker network. LiteLLM reaches
Ollama at `http://ollama:11434`.

### GPU Support

#### WSL2 (recommended for GPU)

WSL2 provides **native GPU access** via GPU paravirtualization (GPU-PV). CUDA
and DirectML work out of the box -- just install the standard NVIDIA Windows
driver on the host. No extra configuration is needed inside WSL2.

To enable GPU in the WSL2 deployment:

```powershell
.\scripts\Install-InsideLLM-WSL.ps1 -AnthropicApiKey "sk-ant-..." -OllamaGpu $true
```

This is the **recommended path for GPU-accelerated local models**.

#### Hyper-V

GPU passthrough on Hyper-V is handled by a companion script (`scripts/Setup-GPU-Passthrough.ps1`)
that runs **after** `terraform apply`. Two modes are available:

| Mode | Command | Host GPU Access | Complexity |
|------|---------|----------------|------------|
| **GPU-PV** (default) | `.\scripts\Setup-GPU-Passthrough.ps1` | Shared (host keeps display) | Simple |
| **DDA** | `.\scripts\Setup-GPU-Passthrough.ps1 -Mode DDA` | Exclusive (host loses GPU) | Advanced |

**GPU-PV (recommended)** shares the GPU between Windows and the VM. The host
keeps using the GPU for display while the VM gets compute access:

```powershell
# After terraform apply:
.\scripts\Setup-GPU-Passthrough.ps1
```

**DDA (full passthrough)** exclusively assigns the GPU to the VM. The host
loses access entirely -- ensure you have integrated graphics or a second GPU:

```powershell
.\scripts\Setup-GPU-Passthrough.ps1 -Mode DDA
```

The script automatically:
1. Detects your NVIDIA GPU
2. Configures the VM for GPU access (stops/starts as needed)
3. SSHs into the VM to install `nvidia-container-toolkit`
4. Verifies GPU visibility inside the VM

To remove the GPU assignment:

```powershell
.\scripts\Setup-GPU-Passthrough.ps1 -Remove
```

After GPU setup, set `ollama_gpu = true` in `terraform.tfvars` and redeploy,
or edit `/opt/InsideLLM/docker-compose.yml` directly.

**WSL2 is still the simpler path for GPU** -- it requires zero extra setup.

Without GPU, models run on CPU (slower but functional for smaller models like Qwen 2.5 14B).

### VM Sizing Guide

| Deployment | vCPU | RAM | Disk | Notes |
|------------|------|-----|------|-------|
| **With Ollama (default)** | 8 | 32 GB | 80 GB | Two local models + Anthropic API |
| **Without Ollama** | 4 | 8 GB | 80 GB | Anthropic API only |
| **With Ollama + GPU** | 8 | 16 GB | 80 GB | GPU handles inference; less RAM needed |

Each Ollama model consumes ~2-5 GB of RAM when loaded. The 32 GB default provides
headroom for two models running concurrently alongside the rest of the stack
(PostgreSQL, Redis, LiteLLM, Open WebUI, Nginx).

---

## 8. Identity & Access Management

### Unified SSO (Single App Registration)

All services share **one IdP app registration** (Azure AD or Okta) — same Client ID and Client Secret. When SSO is configured, users authenticate once and are recognized across all services.

| Service | Protocol | Redirect URI |
|---------|----------|-------------|
| Open WebUI | OIDC | `https://<host>/oauth/oidc/callback` |
| LiteLLM | OIDC | `https://<host>/litellm/sso/callback` |
| Grafana | Generic OAuth | `https://<host>/grafana/login/generic_oauth` |
| Admin Center | OIDC | `https://<host>/auth/callback` |

### Admin Center Authentication (3 Modes)

| Mode | When Active | How It Works |
|------|-------------|-------------|
| **OIDC** | Cloud SSO configured (Azure AD / Okta) | nginx `auth_request` validates JWT session cookie. Login redirects to IdP. |
| **LDAP** | AD domain join enabled, no cloud SSO | Login form authenticates via LDAP bind to AD. Access restricted to `ad_admin_groups`. |
| **Open** | Neither configured (default) | Admin page has no authentication. |

The mode is determined automatically: `sso_provider != "none"` → OIDC, `ad_domain_join == true` → LDAP, neither → open.

### Authentication Layers

```
Layer 1: Nginx (TLS)
+--------------------------------------------+
| HTTPS required for all access              |
| Self-signed or organization CA cert        |
+--------------------------------------------+
          |
          v
Layer 2: Open WebUI (User Authentication)
+--------------------------------------------+
| Self-registration with email + password    |
| First registrant becomes admin             |
| Role-based access: admin / user            |
+--------------------------------------------+
          |
          v
Layer 3: LiteLLM (API Authentication + SSO)
+--------------------------------------------+
| Master key (admin)                         |
| Per-user API keys (team-scoped)            |
| Azure AD SSO (OIDC)                        |
| Okta SSO (OIDC)                            |
+--------------------------------------------+
```

### Azure Active Directory (Microsoft Entra ID) Integration

For organizations using Microsoft 365 / Azure AD:

```
 +---------------------------+         +---------------------------+
 |     Azure AD Tenant       |         |     Inside LLM            |
 |                           |         |                           |
 |  1. Register App          |         |  4. LiteLLM validates     |
 |     - Client ID           |-------->|     token via Microsoft   |
 |     - Client Secret       |         |     OIDC endpoints        |
 |     - Redirect URI        |         |                           |
 |                           |         |  5. User auto-provisioned |
 |  2. User clicks "Login    |         |     with AD email/name    |
 |     with Microsoft"       |         |                           |
 |                           |         |  6. Assigned to team      |
 |  3. Azure AD authenticates|         |     based on AD groups    |
 |     and returns OIDC token|         |     (manual mapping)      |
 +---------------------------+         +---------------------------+
```

**Setup Steps:**

1. In Azure Portal, go to **Azure Active Directory > App Registrations > New**
2. Add all four Redirect URIs from the table above
3. Create a Client Secret under **Certificates & Secrets**
4. Note the Application (Client) ID, Client Secret, and Tenant ID

**Configuration:**

```hcl
# terraform.tfvars
sso_provider           = "azure_ad"
azure_ad_client_id     = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
azure_ad_client_secret = "your-client-secret"
azure_ad_tenant_id     = "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx"
```

**Environment variables injected into LiteLLM:**

| Variable | Source |
|----------|--------|
| `MICROSOFT_CLIENT_ID` | App Registration > Application (client) ID |
| `MICROSOFT_CLIENT_SECRET` | App Registration > Certificates & Secrets |
| `MICROSOFT_TENANT` | Azure AD > Tenant ID |

### Okta Integration

For organizations using Okta as their identity provider:

```
 +---------------------------+         +---------------------------+
 |     Okta Tenant           |         |     Inside LLM            |
 |                           |         |                           |
 |  1. Create OIDC App       |         |  4. LiteLLM validates     |
 |     - Client ID           |-------->|     token via Okta        |
 |     - Client Secret       |         |     OIDC endpoints        |
 |     - Assign users/groups |         |                           |
 |                           |         |  5. User auto-provisioned |
 |  2. User clicks "Login    |         |     with Okta profile:    |
 |     with Okta"            |         |     - sub (user ID)       |
 |                           |         |     - email               |
 |  3. Okta authenticates    |         |     - name (display name) |
 |     and returns OIDC token|         |                           |
 +---------------------------+         +---------------------------+
```

**Setup Steps:**

1. In Okta Admin Console, go to **Applications > Create App Integration**
2. Select **OIDC - OpenID Connect** and **Web Application**
3. Add all four Sign-in redirect URIs from the table above
4. Assign users or groups to the application
5. Note the Client ID, Client Secret, and your Okta domain

**Configuration:**

```hcl
# terraform.tfvars
sso_provider       = "okta"
okta_client_id     = "0oaxxxxxxxxxxxxxxxx"
okta_client_secret = "your-client-secret"
okta_domain        = "your-org.okta.com"
```

**Terraform auto-constructs Okta OIDC endpoint URLs:**

| Variable | Constructed Value |
|----------|------------------|
| `GENERIC_AUTHORIZATION_ENDPOINT` | `https://{okta_domain}/oauth2/v1/authorize` |
| `GENERIC_TOKEN_ENDPOINT` | `https://{okta_domain}/oauth2/v1/token` |
| `GENERIC_USERINFO_ENDPOINT` | `https://{okta_domain}/oauth2/v1/userinfo` |
| `GENERIC_USER_ID_ATTRIBUTE` | `sub` |
| `GENERIC_USER_EMAIL_ATTRIBUTE` | `email` |
| `GENERIC_USER_DISPLAY_NAME_ATTRIBUTE` | `name` |

### Team-Based Access Control

LiteLLM organizes users into teams with distinct permissions, auto-provisioned
on first deployment:

```
+------------------+---------+--------+---------+-----+----------+
| TEAM             | BUDGET  | PERIOD | TPM     | RPM | MODELS   |
+------------------+---------+--------+---------+-----+----------+
| administrators   | unlim.  | 30d    | 500,000 | 100 | ALL      |
+------------------+---------+--------+---------+-----+----------+
| general-users    | $5/day  | 1d     | 100,000 |  30 | Sonnet,  |
|                  |         |        |         |     | Haiku    |
+------------------+---------+--------+---------+-----+----------+
| power-users      | $20/day | 1d     | 200,000 |  60 | ALL      |
+------------------+---------+--------+---------+-----+----------+
```

---

## 9. Security Architecture

### Defense in Depth

```
LAYER 1: Network
+------------------------------------------------------------+
| UFW Firewall: deny all except SSH, HTTP, HTTPS, LiteLLM   |
| Docker bridge: containers isolated on 172.28.0.0/16       |
| Internal Hyper-V switch: VM isolated from LAN (optional)  |
+------------------------------------------------------------+

LAYER 2: Transport
+------------------------------------------------------------+
| TLS 1.2/1.3 only (no TLS 1.0/1.1)                        |
| HSTS enforced (1 year, includeSubDomains)                 |
| HTTP -> HTTPS redirect (301)                              |
| HTTP/2 enabled                                            |
+------------------------------------------------------------+

LAYER 3: Application
+------------------------------------------------------------+
| Security headers: X-Frame-Options, X-Content-Type-Options |
| X-XSS-Protection, Referrer-Policy, HSTS                   |
| WebSocket upgrade support (streaming)                     |
| 50 MB body limit (prevents abuse)                         |
+------------------------------------------------------------+

LAYER 4: Authentication
+------------------------------------------------------------+
| Azure AD / Okta SSO (OIDC)                                |
| Per-user API keys (team-scoped)                           |
| Master key for admin operations                           |
| SSH key-only access (no passwords)                        |
+------------------------------------------------------------+

LAYER 5: Authorization
+------------------------------------------------------------+
| Team-based model access (not all users get Opus)          |
| Role-based UI access (admin / user)                       |
| Community sharing disabled                                |
+------------------------------------------------------------+

LAYER 6: Supply Chain Security
+------------------------------------------------------------+
| SCFW (Supply Chain Firewall) wraps pip inside WSL2        |
| Blocks known-malicious PyPI packages (Datadog dataset)    |
| Warns on packages < 24 hours old                          |
| OSV.dev vulnerability advisory checks                     |
+------------------------------------------------------------+

LAYER 7: Data Protection (DLP)
+------------------------------------------------------------+
| DLP gateway callback: PII, PHI, credentials blocked/redacted|
| Scans inlined file content (messages + extracted text)    |
| Outlet scanning (assistant responses + RAG excerpts)      |
| Custom patterns for org-specific data                     |
+------------------------------------------------------------+

LAYER 8: Cost Protection
+------------------------------------------------------------+
| Per-user daily budgets ($5/day default)                    |
| Global monthly cap ($100/month default)                   |
| Rate limiting: 30 RPM / 100K TPM per user                |
| 80% budget alert via Slack                                |
+------------------------------------------------------------+

LAYER 9: Audit & Observability
+------------------------------------------------------------+
| Netdata real-time monitoring (containers, host, DB, Redis)|
| Langfuse callbacks on every LLM call                      |
| DLP detection logging (without sensitive data)            |
| PostgreSQL spend tracking                                 |
| Docker health checks on all containers                    |
+------------------------------------------------------------+
```

### Secret Management

| Secret | Generation | Storage |
|--------|-----------|---------|
| LiteLLM master key | `random_password` (32 chars, `sk-` prefix) | Terraform state (sensitive) |
| PostgreSQL password | `random_password` (24 chars) | Terraform state (sensitive) |
| WebUI session secret | `random_password` (32 chars) | Terraform state (sensitive) |
| TLS private key | `tls_private_key` (RSA 2048) or BYOC | VM filesystem (mode 0600) |
| Anthropic API key | User-provided | Terraform state (sensitive) |
| SSH private key | User's `~/.ssh/id_rsa` | Never leaves host machine |

---

## 10. Cost Governance & Rate Limiting

### Budget Hierarchy

```
+------------------------------------------------+
| GLOBAL CAP: $100/month                         |
| (hard stop -- no API calls after this)         |
|                                                |
|  +------------------------------------------+  |
|  | TEAM: administrators -- unlimited        |  |
|  +------------------------------------------+  |
|  | TEAM: power-users -- $20/day             |  |
|  +------------------------------------------+  |
|  | TEAM: general-users -- $5/day            |  |
|  |                                          |  |
|  |  +------+  +------+  +------+  +------+  |  |
|  |  |User A|  |User B|  |User C|  |User D|  |  |
|  |  |$5/day|  |$5/day|  |$5/day|  |$5/day|  |  |
|  |  +------+  +------+  +------+  +------+  |  |
|  +------------------------------------------+  |
+------------------------------------------------+
```

### Rate Limiting

```
Per-User Limits (enforced in Redis, sub-millisecond):
+---------------------------------------------+
| Requests per minute (RPM):  30              |
| Tokens per minute (TPM):    100,000         |
| Token counting:             input + output  |
+---------------------------------------------+

System-Wide Limit:
+---------------------------------------------+
| Max parallel requests:      50              |
+---------------------------------------------+

When limits are exceeded:
+---------------------------------------------+
| HTTP 429 Too Many Requests                  |
| Retry-After header included                 |
+---------------------------------------------+
```

### Alerting

When any budget reaches 80% utilization, a Slack notification is sent
automatically via LiteLLM's built-in alerting system.

---

## 11. Deployment & Operations

### Setup Wizard (Recommended)

Open **`html/Setup.html`** in your browser for a guided, step-by-step configuration wizard.
It walks you through all deployment options and generates the config file
(`terraform.tfvars` or PowerShell command) ready to download. No command-line
knowledge needed to configure -- just fill in the form and click Download.

> **Single-VM users:** the Setup Wizard above is all you need. The fleet workflow below is for multi-VM deployments only.

### Multi-VM Fleet Deployment

When deploying two or more InsideLLM VMs (e.g., per-department instances sharing a central MSSQL database), use the YAML-driven fleet manifest instead of generating individual tfvars files by hand.

**Structure:** `fleet.yaml` at the repository root contains a `shared:` block (settings common to every VM) and an `instances:` list (per-VM overrides). Instance keys override shared keys. Any variable from `terraform/variables.tf` may appear in either block.

```yaml
shared:
  hyperv_user:  "uniformedi\\dmedina"
  vm_gateway:   "10.0.0.1"
  governance_hub_central_db_host: "10.0.0.6"
  ad_join_password: "env:FLEET_AD_PASSWORD"   # resolved from env at render time

instances:
  - vm_name: insidellm-tech
    vm_static_ip: "10.0.0.120/24"
    anthropic_api_key: "sk-ant-api03-..."
  - vm_name: insidellm-primary
    vm_static_ip: "10.0.0.122/24"
    anthropic_api_key: "sk-ant-api03-..."
```

**Workflow:**

```powershell
# 1. Set secret environment variables (not stored in fleet.yaml)
$env:FLEET_AD_PASSWORD    = Read-Host -AsSecureString | ConvertFrom-SecureString -AsPlainText
$env:FLEET_MSSQL_PASSWORD = Read-Host -AsSecureString | ConvertFrom-SecureString -AsPlainText

# 2. Render per-VM tfvars from the manifest
pwsh ./scripts/Render-Fleet.ps1 -ManifestPath ./fleet.yaml

# 3. Deploy all VMs (sequential by default)
pwsh ./scripts/Deploy-Fleet.ps1

# Or deploy a single VM
pwsh ./scripts/Deploy-Fleet.ps1 -TargetVM insidellm-tech

# Dry-run: plan only, no changes
pwsh ./scripts/Deploy-Fleet.ps1 -DryRun

# Destroy a specific VM
pwsh ./scripts/Deploy-Fleet.ps1 -TargetVM insidellm-tech -Destroy
```

**Environment variables for secrets:**

| Variable | Maps to | Purpose |
|----------|---------|---------|
| `FLEET_AD_PASSWORD` | `ad_join_password` | AD domain join credential |
| `FLEET_MSSQL_PASSWORD` | `governance_hub_central_db_password` | Central fleet DB credential |
| `FLEET_ANTHROPIC_KEY` | `anthropic_api_key` (optional) | Shared API key (if not per-VM) |

Each rendered VM gets an isolated Terraform state file (`fleet-out/<vm_name>/terraform.tfstate`), so VM lifecycles are fully independent.

#### Edge + Departments (Tier-1 Fleet Modularity)

For larger fleets you can declare a **front-door router topology** and a **department-to-backend map** alongside `instances:`. Render-Fleet.ps1 uses these two optional blocks to automatically assign `vm_role`, `department`, `fallback_department`, and `fleet_primary_host` to each instance, so you do not have to hand-wire the routing:

```yaml
edge:
  vms:
    - 10.0.0.100                       # primary edge VM (MASTER)
    # - 10.0.0.101                     # optional secondary for keepalived HA
  vip: 192.168.100.109                       # virtual IP owned by keepalived
  domain: insidellm.corp.example.com
  tls_source: self-signed              # self-signed | letsencrypt | custom

departments:
  engineering:
    backend: insidellm-gateway
    fallback: insidellm-gen            # if eng is down, route to general pool
  legal:
    backend: insidellm-legal           # no fallback - legal enforces its own DLP
  exec:
    backend: insidellm-primary

instances:
  - vm_name: insidellm-gen             # auto vm_role = "primary"
    vm_static_ip: "192.168.100.110/24"
  - vm_name: insidellm-gateway             # auto vm_role = "gateway", department = "engineering"
    vm_static_ip: "10.0.0.120/24"
  - vm_name: insidellm-edge            # auto vm_role = "edge" (IP matches edge.vms[0])
    vm_static_ip: "10.0.0.100/24"
```

**Roles:**

| Role | Meaning |
|------|---------|
| `primary` | Runs the central Gov-Hub, Grafana, Loki. Every other VM's `fleet_primary_host` points here. |
| `gateway` | Department-specific backend (Open WebUI + LiteLLM + OPA). Sits behind the edge; not reachable directly from clients. |
| `workstation` | Per-user desktop-class VM (lighter footprint, no central services). |
| `voice` | Voice / agent inference node. |
| `storage` | Central data-plane node (shared object storage). |
| `edge` | Front-door router. Terminates TLS for `edge.domain`, owns the keepalived VIP, and proxies to the correct backend based on OIDC claim / LDAP group. Deployed **last**. |

**Role inference rules:** explicit `vm_role` on an instance always wins. Otherwise the renderer picks the first non-edge/non-workstation VM as `primary`, stamps `gateway` on any VM named as a `departments.*.backend`, and stamps `edge` on any VM whose IP matches `edge.vms`.

**Deploy order (-Stage flag):** stages always run **primary -> backends -> edge** so that backend IPs exist before the router boots.

```powershell
# Deploy everything in the right order
pwsh ./scripts/Deploy-Fleet.ps1 -Stage all      # default

# Or phase it out
pwsh ./scripts/Deploy-Fleet.ps1 -Stage primary  # just the Gov-Hub node
pwsh ./scripts/Deploy-Fleet.ps1 -Stage backends # everything except edge VMs
pwsh ./scripts/Deploy-Fleet.ps1 -Stage edge     # only the edge VMs

# Destroy order: edge first so clients get a clean failure, then backends
pwsh ./scripts/Deploy-Fleet.ps1 -Stage edge -Destroy
pwsh ./scripts/Deploy-Fleet.ps1 -Stage backends -Destroy
```

Render-Fleet.ps1 also writes `fleet-out/_edge-routes.json` (department -> backend-IP map) that the edge VM's cloud-init templates consume.

#### Joining a new VM to an existing fleet

Use `Join-Fleet.ps1` to bootstrap a new VM against a running fleet without hand-editing tfvars:

```powershell
# 1. On the fleet primary, mint a single-use token (valid 24h)
curl -k -X POST https://insidellm-gen/governance/api/v1/fleet/registration-token `
     -H "Content-Type: application/json" -d '{"hours": 24}'

# 2. On the new VM (or the operator workstation):
pwsh ./scripts/Join-Fleet.ps1 `
    -Leader 192.168.100.110 `
    -Token reg-xxxxxxxxxxxxxxxx `
    -Role gateway `
    -Department engineering `
    -VmName insidellm-gateway2 `
    -StaticIp 10.0.0.127/24 `
    -Insecure

# 3. Apply the generated tfvars
cd ./fleet-out/insidellm-gateway2
terraform -chdir=../../terraform apply -var-file=./terraform.tfvars -state=./terraform.tfstate
```

Join-Fleet.ps1 POSTs the token to the primary's `/governance/api/v1/fleet/register` endpoint, decrypts the returned central DB password, writes `fleet-out/<VmName>/terraform.tfvars` with `vm_role`, `department`, `fleet_primary_host`, and the fleet DB connection info, and appends an `instances:` entry to your local `fleet.yaml` for record-keeping. If the primary is running a build whose registration endpoint does not yet expose a full bootstrap payload, the script prints a clear TODO and exits without writing incomplete tfvars.

### Prerequisites

| Requirement | Details |
|-------------|---------|
| Windows 11 Pro or Server 2022+ | Hyper-V capable |
| 48 GB+ host RAM | 32 GB for VM + headroom (16 GB+ sufficient without Ollama) |
| 100 GB+ free disk | VM disk + images |
| Terraform >= 1.5 | IaC tool |
| WSL2 | For genisoimage (cloud-init ISO creation) |
| Anthropic API key | From console.anthropic.com |

### Deployment

```powershell
# 1. Open html/Setup.html in your browser and generate terraform.tfvars
#    Save it to the terraform/ directory
#    NOTE: Set `owner` to your real org name (e.g. "Uniformedi LLC"). It is a
#    label only — stamped into the self-signed TLS cert's O= field and
#    deployment metadata — NOT a Linux user. Leaving it as "CHANGE_ME" works
#    but shows up in browser cert dialogs. /opt/InsideLLM is always root-owned
#    regardless of this value.

# 2. Run prerequisites + deploy (requires admin)
.\scripts\SetupInstall.ps1
# This script: enables Hyper-V, downloads Ubuntu image, configures WinRM,
# then automatically runs terraform init → plan → apply from terraform/
```

For manual terraform commands, run from the `terraform/` directory:

```powershell
cd terraform
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

### Auto-Start on Boot

The stack is configured as a **systemd service** on the VM:

```
 VM Boot -> systemd -> InsideLLM.service -> docker compose up -d
```

All containers have `restart: always`, so individual container crashes
are automatically recovered.

**Log rotation:** The LiteLLM container uses Docker's `json-file` logging
driver with a 50 MB per-file limit and 3-file rotation (150 MB max). This
prevents debug-level logging from filling the disk.

### Updating Services

All containerized services use rolling-release tags (`:latest` or `:main-latest`),
so updating to the newest versions is straightforward.

**Update all services:**

```bash
# SSH into the VM
ssh insidellm-admin@<vm-ip>

# Pull latest images and recreate containers
cd /opt/InsideLLM
sudo docker compose pull
sudo docker compose up -d
```

**Update a single service** (e.g., Open WebUI only):

```bash
sudo docker compose pull open-webui
sudo docker compose up -d open-webui
```

**What gets updated:**

| Service | Image Tag | What Changes |
|---------|-----------|-------------|
| Open WebUI | `ghcr.io/open-webui/open-webui:latest` | Chat UI, pipeline engine, RAG |
| LiteLLM | `ghcr.io/berriai/litellm:main-latest` | API gateway, admin dashboard, budget engine |
| PostgreSQL | `postgres:16-alpine` | Database engine (data preserved on volume) |
| Redis | `redis:7-alpine` | Cache engine (data preserved on volume) |
| Nginx | `nginx:1.27-alpine` | Reverse proxy |

**Important notes:**

- **Data is preserved** -- PostgreSQL, Redis, and Open WebUI data live on
  Docker volumes (`/opt/InsideLLM/data/`), so container recreation
  does not lose data
- **Configuration is preserved** -- config files are bind-mounted from the
  host filesystem, not baked into images
- **DLP configuration persists** -- the gateway callback is configured via `config.yaml`
  and environment variables; changes survive container updates
- **Downtime** -- expect 30-60 seconds of downtime while containers restart.
  Services with health checks will wait for dependencies before starting
- **Rollback** -- if an update causes issues, you can pin a specific image
  version in `/opt/InsideLLM/docker-compose.yml` (e.g.,
  `ghcr.io/open-webui/open-webui:v0.5.10`) and recreate

**Verify after update:**

```bash
# Check all containers are healthy
sudo docker ps --format 'table {{.Names}}\t{{.Status}}\t{{.Image}}'

# Check service health
curl -sk https://localhost/nginx-health         # Nginx
curl -sk https://localhost/litellm/health/liveliness  # LiteLLM
curl -sk https://localhost/health               # Open WebUI (via Nginx)
```

### Health Monitoring

| Container | Health Check | Interval |
|-----------|-------------|----------|
| PostgreSQL | `pg_isready -U litellm` | 10s |
| Redis | `redis-cli ping` | 10s |
| LiteLLM | `python3 urllib > /health/liveliness` | 15s |
| Open WebUI | `curl > /health` | 15s |
| Netdata | `curl > /api/v1/info` | 15s |
| Nginx | Depends on Open WebUI health | -- |

External monitoring endpoints:
- `http://<host>/health` (Nginx HTTP)
- `https://<host>/nginx-health` (Nginx HTTPS)

### File Structure

```
InsideLLM/
+-- README.md                           # This document
+-- README.html                         # Visual landing page
+-- VERSION                             # Platform version (e.g., 3.1.0)
+-- LICENSE                             # BSL 1.1 (converts to Apache 2.0 on 2030-04-11)
+-- NOTICE                              # IP provenance, SAIVAS attribution, third-party licenses
+-- terraform/                          # Terraform infrastructure-as-code
|   +-- main.tf                         # Root module: VM + provisioning
|   +-- variables.tf                    # All input variables
|   +-- outputs.tf                      # VM IP, URLs, secrets
|   +-- providers.tf                    # Hyper-V provider config
|   +-- terraform.tfvars.example        # Template for your values
+-- scripts/                            # User-facing PowerShell scripts
|   +-- SetupInstall.ps1             # Setup, prerequisites, and terraform deploy
|   +-- New-CloudInitIso.ps1        # PowerShell-native cloud-init ISO builder
|   +-- Initialize-InsideLLM.ps1        # Standalone: WSL2 + Docker + SCFW + TLS
|   +-- Install-InsideLLM.ps1           # Generated wrapper (from Setup Wizard)
|   +-- Install-InsideLLM-WSL.ps1       # Full WSL2 deployment
|   +-- Port-Forward-InsideLLM.ps1      # Expose services to LAN
|   +-- Setup-GPU-Passthrough.ps1       # GPU-PV / DDA passthrough
|   +-- Join-ADDomain.ps1              # Active Directory domain join
|   +-- provision-monitoring.sh         # Idempotent monitoring/alerting setup
+-- html/                               # Browser-facing UI files
|   +-- Setup.html                      # Interactive setup wizard (9 steps)
|   +-- admin.html                      # Admin command center SPA (6 tabs, 4 themes)
+-- markdown/                           # Documentation
|   +-- policyengine.md                 # OPA policy engine normative spec
|   +-- images/BlockedDLP.png           # DLP screenshot
+-- templates/                          # Terraform .tpl templates
|   +-- docker-compose.yml.tpl          # All Docker services definition
|   +-- post-deploy.sh.tpl             # Post-deploy: teams, tools, systemd
+-- configs/                            # Service configuration files
    +-- cloud-init/                     # VM first-boot provisioning
    |   +-- user-data.yaml.tpl          # Main VM cloud-init
    |   +-- ollama-user-data.yaml.tpl   # Ollama VM cloud-init
    |   +-- meta-data.yaml.tpl          # Cloud-init identity
    |   +-- network-config.yaml.tpl     # Static IP configuration
    +-- docforge/                       # Node.js file generation service
    +-- governance-hub/                 # FastAPI governance service
    |   +-- migrations/                 # Central DB migrations (platform_version, etc.)
    |   +-- src/routers/auth.py         # Admin auth (OIDC + LDAP + open modes)
    |   +-- src/services/auth_service.py  # JWT sessions + LDAP bind
    |   +-- src/services/oidc_service.py  # OIDC discovery + code exchange
    +-- grafana/                        # Dashboards + datasource provisioning
    +-- litellm/                        # API gateway config template
    +-- loki/                           # Log aggregation config
    +-- nginx/                          # Reverse proxy + TLS template
    +-- opa/                            # Open Policy Agent (Humility + industry)
    |   +-- policies/humility/          # Mandatory alignment policy (Rego)
    |   +-- policies/industry/          # HIPAA, FDCPA, SOX, PCI, FERPA, GLBA
    |   +-- policies/decision.rego      # Decision aggregation
    +-- open-webui/                     # Optional frontend filters + 6 tool integrations
    |   +-- dlp-pipeline.py             # DLP filter (legacy, inactive by default)
    |   +-- docforge-tool.py            # File generation/conversion
    |   +-- governance-advisor-tool.py  # AI governance analysis
    |   +-- fleet-management-tool.py    # Cross-instance management
    |   +-- system-designer-tool.py     # Deployment planning + cost modeling
    |   +-- data-connector-tool.py      # External data source queries
    |   +-- opa-policy-pipeline.py      # Policy enforcement filter
    +-- promtail/                       # Log shipping config
    +-- trivy/                          # CVE scan script
```

---

## 11a. WSL2 Deployment (Alternative)

For a lighter-weight deployment without Terraform or Hyper-V, InsideLLM can run
entirely inside WSL2 on Windows 11. This deploys the same Docker containers and
configuration as the Hyper-V path.

### When to Use WSL2 vs Hyper-V

| | WSL2 | Hyper-V (Terraform) |
|--|------|---------------------|
| **Best for** | Developer workstations, evaluation, small teams | Production, shared servers, multi-VM hosts |
| **Prerequisites** | Windows 11 22H2+, no Terraform needed | Windows Pro/Server, Terraform, Hyper-V |
| **Setup time** | ~5 minutes (one script) | ~15 minutes (Terraform plan/apply) |
| **Isolation** | Shared kernel with Windows | Full VM isolation |
| **GPU support** | Native GPU-PV (just install Windows NVIDIA driver) | Requires manual DDA setup (advanced) |
| **Networking** | WSL2 dynamic IP (refreshed via scheduled task) | Static IP on Hyper-V internal switch |
| **Resource control** | `.wslconfig` limits | Terraform variables (CPU, RAM, disk) |

### Prerequisites

| Requirement | Notes |
|-------------|-------|
| Windows 11 22H2+ | WSL2 with systemd support |
| 16 GB+ RAM (without Ollama) or 48 GB+ (with Ollama) | Same as Hyper-V path |
| Anthropic API key | From https://console.anthropic.com |

### Quick Start

```powershell
# Run as Administrator -- full deployment in one step:
powershell -ExecutionPolicy Bypass -File .\scripts\Install-InsideLLM-WSL.ps1 -AnthropicApiKey "sk-ant-api03-..."
```

That's it. The script handles WSL2 installation, Docker setup, SCFW deployment,
TLS certificate generation, config generation, container deployment, and port
forwarding automatically.

#### Separate Initialization (Optional)

To provision the base environment (WSL2, Docker, SCFW, TLS) without deploying
the application stack, use the standalone initialization script:

```powershell
# Run as Administrator -- infrastructure only:
powershell -ExecutionPolicy Bypass -File .\scripts\Initialize-InsideLLM.ps1

# Then deploy the stack later:
powershell -ExecutionPolicy Bypass -File .\scripts\Install-InsideLLM-WSL.ps1 -AnthropicApiKey "sk-ant-api03-..."
```

Both scripts are idempotent -- `Install-InsideLLM-WSL.ps1` will skip any steps
already completed by `Initialize-InsideLLM.ps1`.

### Disabling Ollama for a lighter deployment

```powershell
.\scripts\Install-InsideLLM-WSL.ps1 -AnthropicApiKey "sk-ant-..." -EnableOllama $false
```

### All Parameters

| Parameter | Default | Description |
|-----------|---------|-------------|
| `AnthropicApiKey` | *(required)* | Anthropic API key |
| `EnableOllama` | `$true` | Enable local Ollama models |
| `OllamaModels` | `qwen2.5-coder:14b, qwen2.5:14b` | Models to pull |
| `EnableHaiku` | `$true` | Include Claude Haiku |
| `EnableOpus` | `$true` | Include Claude Opus |
| `GlobalMaxBudget` | `100` | Monthly budget (USD) |
| `DefaultUserBudget` | `5.0` | Daily per-user budget (USD) |
| `SsoProvider` | `none` | SSO: `none`, `azure_ad`, or `okta` |
| `Hostname` | `InsideLLM` | Hostname for TLS cert |
| `Domain` | `local` | Domain for FQDN |
| `Uninstall` | *(switch)* | Remove everything |
| `SkipPortForwarding` | *(switch)* | Skip netsh/firewall rules |

### Known Limitations

- **WSL2 IP changes on restart** -- a scheduled task automatically refreshes port
  forwarding rules on login. If LAN access breaks after a reboot, run
  `.\scripts\Install-InsideLLM-WSL.ps1 -AnthropicApiKey "..." -SkipPortForwarding:$false`
  to refresh manually.
- **Shared kernel** -- WSL2 shares the Windows kernel, so it is less isolated
  than a full Hyper-V VM. For production or compliance-sensitive environments,
  use the Hyper-V path.
- **Memory** -- WSL2 can consume more host memory than expected. Add a
  `C:\Users\<you>\.wslconfig` to set limits:
  ```ini
  [wsl2]
  memory=8GB        # Without Ollama
  # memory=32GB     # With Ollama
  ```

### Uninstall

```powershell
.\scripts\Install-InsideLLM-WSL.ps1 -Uninstall
```

This removes all containers, configs, port forwarding rules, and firewall rules.
The WSL2 distro itself is preserved (remove it with `wsl --unregister InsideLLM`).

---

## 12. Product Use Case

### Target Customer Profile

| Attribute | Description |
|-----------|-------------|
| **Organization size** | 10-500 employees |
| **Industry** | Healthcare, Finance, Legal, Government -- regulated sectors |
| **IT infrastructure** | Existing Windows Server / Hyper-V environment |
| **Pain point** | Want AI capabilities but cannot send sensitive data to cloud AI |
| **Budget** | Controls on AI spend are a hard requirement |
| **Compliance** | HIPAA, PCI-DSS, SOX, or internal data governance policies |

### Value Proposition

```
+================================================================+
|                                                                |
|  "Enterprise AI with Guardrails"                               |
|                                                                |
|  Give your entire organization access to Claude AI             |
|  while maintaining complete control over:                      |
|                                                                |
|    [x] What data leaves your network (DLP)                     |
|    [x] Who can access AI (Azure AD / Okta SSO)                |
|    [x] How much each person spends (per-user budgets)          |
|    [x] What models each team can use (role-based access)       |
|    [x] Full audit trail of every interaction (Langfuse)        |
|                                                                |
|  Deployed on YOUR infrastructure. YOUR rules.                  |
|                                                                |
+================================================================+
```

### Competitive Comparison

| Feature | Inside LLM | Direct API | ChatGPT Enterprise |
|---------|---------------|------------|-------------------|
| DLP scanning | Messages + files (Excel, PDF, etc.) | None | Limited |
| SSO (Azure AD) | Yes (OIDC) | N/A | Yes |
| SSO (Okta) | Yes (OIDC) | N/A | Yes |
| Per-user budgets | Yes ($5/day default) | No | No |
| Per-user rate limits | Yes (RPM + TPM) | No | No |
| Team-based model access | Yes | No | Limited |
| On-premises deployment | Yes (Hyper-V) | N/A | No (cloud only) |
| Audit trail | Full (Langfuse) | Manual | Limited |
| File upload scanning | Excel, PDF, Word, CSV, PPTX | No | No |
| Document Q&A (RAG) | Local embeddings, full-context | N/A | Yes (cloud) |
| Custom DLP patterns | Yes (regex) | No | No |
| Self-hosted | Yes | N/A | No |
| Cost | FOSS + API usage | API only | Per-seat licensing |
| Setup time | ~30 minutes | N/A | Weeks (enterprise sales) |

### ROI Model

```
COST SAVINGS
+-------------------------------------------------------------+
| Without guardrails:                                         |
|   - Uncontrolled API spend: $2,000-10,000/month             |
|   - Data breach (PII leak): $150+ per record (IBM 2025)     |
|   - Compliance violation: $50K-$1.5M per incident           |
|                                                             |
| With Inside LLM:                                  |
|   - Controlled spend: $100/month global cap (configurable)  |
|   - DLP scans messages AND files (Excel, PDF, Word, etc.)   |
|   - Audit trail satisfies compliance requirements           |
|   - Infrastructure cost: ~$0 (runs on existing Hyper-V)     |
+-------------------------------------------------------------+
```

### Compliance Mapping

| Regulation | Requirement | How the Stack Addresses It |
|------------|-------------|---------------------------|
| **HIPAA** | PHI must not be disclosed to unauthorized parties | DLP blocks MRN, DOB, ICD codes in messages and uploaded files |
| **PCI-DSS** | Cardholder data must be protected | DLP blocks credit cards and bank accounts in messages and files |
| **SOX** | Audit trail for financial data access | Langfuse logs every API call; DLP logs detections |
| **GDPR** | Personal data processing must be lawful and limited | DLP blocks SSNs and PII in messages and files; per-user controls |
| **Internal Policy** | Only authorized employees access AI | SSO via Azure AD or Okta; team-based permissions |
| **Budget Control** | AI spend must be predictable | Per-user daily caps, global monthly cap, Slack alerts |

---

## 13. DocForge (File Generation & Conversion)

DocForge is a Node.js microservice with LibreOffice headless that runs as a Docker container in the stack. Claude can generate and convert files directly from chat via an Open WebUI Tool.

### Supported Formats

| Category | Generate | Convert To/From |
|----------|----------|-----------------|
| Office | DOCX, XLSX, PPTX | All Office + PDF + ODF |
| ODF | ODT, ODS, ODP | Via LibreOffice conversion |
| PDF | Native (PDFKit) | From any Office/ODF format |
| Text | CSV, JSON, XML, YAML, Markdown, TXT | Between text formats |

### API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/docforge/api/generate` | POST | Generate files from structured JSON |
| `/docforge/api/convert` | POST | Convert uploaded files between formats |
| `/docforge/api/formats` | GET | List supported formats |

### Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `docforge_enable` | `true` | Enable the DocForge service |
| `docforge_max_file_size_mb` | `50` | Max upload size for conversions |

LibreOffice conversions are serialized via an async queue to prevent conflicts. Temp files are cleaned every 30 minutes.

---

## 14. AI Governance & Compliance

### Governance Tier Classification

The Setup Wizard collects governance metadata aligned with the AI Governance Framework:

| Variable | Options | Description |
|----------|---------|-------------|
| `industry` | 12 presets | Drives keyword templates and governance defaults |
| `governance_tier` | `tier1`, `tier2`, `tier3` | Controls strictness (full, standard, lightweight) |
| `data_classification` | `public`, `internal`, `confidential`, `restricted` | Highest data sensitivity handled |
| `ai_ethics_officer` | free text | Named individual for incident escalation |
| `log_retention_days` | 365-2555 | Audit trail retention (Tier 1 requires 3-7 years) |

### Industry Keyword Templates

Selecting an industry in the wizard pre-loads curated keyword dictionaries:

| Industry | Example Keywords | Default Tier |
|----------|-----------------|-------------|
| Collections | fdcpa, settlement, garnishment, mini-miranda | Tier 1 |
| Healthcare | hipaa, phi, diagnosis, adverse event, breach notification | Tier 1 |
| Financial | aml, bsa, sar, kyc, adverse action, dodd-frank | Tier 1 |
| Legal | litigation, privilege, deposition, malpractice | Tier 1 |
| Government | foia, fedramp, clearance, inspector general | Tier 1 |
| Insurance | claims, subrogation, actuarial, naic | Tier 1 |
| Education | ferpa, student record, plagiarism, title ix | Tier 2 |
| Real Estate | fair housing, escrow, zoning, eviction | Tier 2 |
| Retail | pci, chargeback, false advertising, fulfillment | Tier 2 |
| Manufacturing | osha, capa, iso 9001, lockout tagout | Tier 2 |
| General | *(no preset — built-in defaults only)* | Tier 3 |

### Keyword Analysis

Every API request is analyzed via PostgreSQL full-text search against a keyword dictionary:

- `message_content` view extracts user messages from JSONB with `ts_vector`
- `keyword_matches` joins against the dictionary using `plainto_tsquery`
- `keyword_daily_summary` materialized view refreshed every 15 minutes
- `flagged_requests` view filters high/critical severity matches for compliance review

### Automated Operations Stack

| Service | Purpose | Schedule |
|---------|---------|----------|
| Watchtower | Auto-pull container image updates | Daily 4 AM |
| Trivy | CVE scan all running images | Daily 5 AM |
| Grafana + Loki | Centralized logging + compliance dashboards | Continuous |
| Uptime Kuma | Service health monitoring + alerting | Continuous |
| PostgreSQL backup | `pg_dump` with 30-backup retention | Daily/Weekly |

All operations services are toggled via Terraform variables (`ops_watchtower_enable`, etc.).

---

## 15. Enterprise Governance Hub

The Governance Hub is a FastAPI microservice (`governance-hub` container) that provides enterprise-wide AI governance management. Enabled via `governance_hub_enable = true`.

### Central Repository Sync

Exports governance telemetry to a central database on a configurable schedule:

| Variable | Default | Description |
|----------|---------|-------------|
| `governance_hub_central_db_type` | `postgresql` | `postgresql`, `mariadb`, or `mssql` |
| `governance_hub_central_db_host` | *(empty)* | Central DB hostname |
| `governance_hub_sync_schedule` | `0 */6 * * *` | Cron schedule (every 6 hours) |

Data exported: spend logs, user counts, DLP blocks, keyword flags, compliance scores, config snapshots.

### Change Management Workflow

Formal proposal/approval pipeline for governance framework changes:

1. **Propose** — human or AI advisor creates a change proposal
2. **Review** — supervisor reviews with impact assessment
3. **Approve/Reject** — decision recorded with reviewer name, email, comments
4. **Implement** — creates a new framework version with full audit trail

All state transitions are recorded in the hash-chained audit trail.

### Hash-Chained Audit Integrity

Every governance event is appended to an immutable SHA-256 chain:

```
chain_hash = SHA-256(sequence || event_type || payload_hash || previous_hash)
```

Tampering with any record breaks the chain. The `/audit/chain/verify` endpoint detects the first broken link. Checkpoints are created every 100 entries for efficient partial verification.

### Fleet Management

Cross-instance visibility via the central database. Each instance syncs its `platform_version` to the central DB, enabling fleet-wide version tracking and outdated instance detection.

| Endpoint | Purpose |
|----------|---------|
| `GET /fleet/instances` | List all registered InsideLLM deployments (includes `platform_version`) |
| `GET /fleet/summary` | Fleet-wide aggregate metrics |
| `GET /fleet/db/config` | Current central DB configuration (password masked) |
| `POST /fleet/db/test` | Test connection to a fleet database (MSSQL/MariaDB/PostgreSQL) |
| `PUT /fleet/db/config` | Save central DB config to env override file |
| `POST /fleet/compare` | Compare configs across instances |
| `POST /restore/generate-tfvars` | Generate terraform.tfvars from any config snapshot |
| `POST /restore/clone-from-node` | Fetch config snapshot from a source instance for node replacement |
| `GET /restore/snapshots/{id}` | List available config snapshots for an instance |

**Fleet Database Setup Wizard:** The Admin Command Center's Fleet tab includes a built-in wizard to configure the central fleet database. Supports MS SQL Server (with TrustServerCertificate and Encrypt options), MariaDB/MySQL, and PostgreSQL. Includes Test Connection and Save Configuration buttons.

**Node Replacement:** When a new InsideLLM instance connects to the fleet, it can clone the governance configuration from the node it replaces via the "Clone Config" button in the fleet table. The wizard allows selecting a snapshot, previewing config sections, and downloading a terraform.tfvars with the cloned configuration.

### AI Governance Advisor

Open WebUI Tool that analyzes telemetry and suggests framework improvements. All suggestions enter the change management pipeline as pending proposals — AI never makes changes directly.

### AI System Designer

Open WebUI Tool for planning deployments:

- `design_deployment` — natural language requirements to architecture + terraform.tfvars
- `estimate_costs` — monthly cost projections by user count and model tier
- `recommend_config` — optimized settings for industry + compliance level
- `plan_fleet` — multi-instance architecture with per-instance configurations

---

## 15a. Gov-Hub Role-Based Access

The Governance Hub enforces three RBAC roles on its APIs and admin UI:

| Role       | Permissions                                      | Default AD group    | OIDC override variable        |
|------------|--------------------------------------------------|---------------------|-------------------------------|
| `view`     | GET-only across all gov-hub endpoints            | `InsideLLM-View`    | `oidc_view_group_ids`         |
| `admin`    | CRUD everywhere *except* change approve/reject   | `InsideLLM-Admin`   | `oidc_admin_group_ids`        |
| `approver` | `POST /api/v1/changes/{id}/approve` and `/reject`| `InsideLLM-Approve` | `oidc_approver_group_ids`     |

A user's roles are the **union** of all matching groups; `admin` and `approver` both imply `view`. Users in no matching group receive HTTP 403.

**OIDC overrides** take group object IDs (Azure AD GUIDs), matched against the `groups` claim in the id_token. Set them as lists in `terraform.tfvars`, e.g.:

```hcl
oidc_admin_group_ids = ["11111111-2222-3333-4444-555555555555"]
```

**Backcompat:** Deployments that set only `ad_admin_groups` continue to work — users in that group are granted all three roles, and a WARNING is logged the first time the fallback fires.

### Break-Glass Local Account

A static local account `insidellm-admin` is always available, independent of LDAP/OIDC health. Its password equals the current value of `LITELLM_MASTER_KEY` (in `/opt/InsideLLM/.env`). In Governance Hub it carries all three roles.

- Use it to recover access when SSO/AD is broken.
- Every successful login is recorded at INFO level in the gov-hub log **and** appended to `governance_audit_chain` with `event_type=break_glass_login` (tamper-evident SHA-256 chain).
- **Security:** rotate `LITELLM_MASTER_KEY` after any incident use. The account cannot be disabled — it exists specifically for lockout recovery. Protect your master key accordingly.

Authenticate via HTTP Basic:

```bash
curl -u insidellm-admin:$LITELLM_MASTER_KEY https://<vm>/governance/auth/token
# → {"access_token":"<jwt>","token_type":"bearer","roles":["admin","approver","view"]}
```

Use the returned JWT as `Authorization: Bearer <jwt>` on subsequent API calls.

### Break-Glass Admin Across Bundled Subsites

In addition to Governance Hub, the post-deploy script seeds the same `insidellm-admin` / `$LITELLM_MASTER_KEY` account as a local administrator in every bundled service that maintains its own auth database. This gives operators a single emergency credential when SSO is down or a service's remote auth integration is misconfigured.

| Service     | Login URL                         | Username          | Password              | Role/Scope         |
|-------------|-----------------------------------|-------------------|-----------------------|--------------------|
| Grafana     | `https://<vm>/grafana/login`      | `insidellm-admin` | `$LITELLM_MASTER_KEY` | Server admin       |
| Open WebUI  | `https://<vm>/`                   | `insidellm-admin@local` | `$LITELLM_MASTER_KEY` | `admin`         |
| LiteLLM UI  | `https://<vm>/litellm/ui`         | `insidellm-admin` | `$LITELLM_MASTER_KEY` | `proxy_admin`      |
| Uptime Kuma | `https://<vm>/status/`            | `insidellm-admin` | `$LITELLM_MASTER_KEY` | Superadmin         |
| pgAdmin     | `http://<vm>:5050`                | `insidellm-admin@local` | `$LITELLM_MASTER_KEY` | pgAdmin admin   |

**Rotation.** To change the break-glass password:

```bash
# On the VM
sudo sed -i 's/^LITELLM_MASTER_KEY=.*/LITELLM_MASTER_KEY=<new-value>/' /opt/InsideLLM/.env
cd /opt/InsideLLM && sudo docker compose up -d
sudo bash /opt/InsideLLM/post-deploy.sh    # re-seeds all five services idempotently
```

The seed logic is idempotent: on every deploy it updates the account's password in place if the master key has changed, and creates it if it's missing.

**Security warning.** Compromise of `LITELLM_MASTER_KEY` compromises all five services plus the LiteLLM proxy itself. This account is intentionally un-disable-able — it exists only for lockout recovery. Treat the master key as a tier-0 secret: store it in a hardware-backed vault, restrict `/opt/InsideLLM/.env` to `root:root 0600`, and rotate immediately after any incident use or suspected exposure.

---

## 16. OPA Policy Engine

Open Policy Agent (OPA) enforcement based on the `markdown/policyengine.md` normative specification. Enabled via `policy_engine_enable = true`.

OPA is a **pure, side-effect-free policy evaluation engine**. It receives input, evaluates Rego rules, and returns a structured decision — it never logs, persists, filters, or calls external systems. This separation ensures policy rules are testable offline (`opa test`), replayable, auditable, and fast (<5ms). All side effects (logging, redacting, blocking, queueing) are executed by the InsideLLM enforcement pipeline *after* OPA returns its decision. See `markdown/policyengine.md` Section 1.1 for the full rationale.

### Architecture

```
User Message → DLP Pipeline → OPA Pipeline → LiteLLM → Claude
                                    │
                              ┌─────▼─────┐
                              │ OPA :8181  │
                              │ Humility   │  (always on)
                              │ + Industry │  (toggled)
                              └─────┬─────┘
                                    │
                              Decision + Obligations
```

### Humility Policy (Mandatory)

The Humility policy is implemented as a standalone MIT-licensed pip package
([`humility-guardrail`](https://github.com/uniformedi/humility-guardrail)) that the LiteLLM
container installs at startup. The InsideLLM callbacks (`humility_prompt.py` and `humility_guardrail.py`)
are thin subclasses that add Redis prompt loading, OPA delegation, and governance-hub audit logging
on top of the canonical implementation.

Always loaded, cannot be disabled. Denies when:
- Metaphysical context produces directives
- High-confidence output lacks uncertainty declaration
- Authority or superiority is claimed
- High-impact output lacks documented human consensus
- Asymmetric persuasion is attempted

### Industry Policies

Toggled via `policy_engine_industry_policies`:

| Policy | Regulation | Key Controls |
|--------|-----------|--------------|
| `hipaa` | HIPAA | PHI filtering, break-glass audit, authorization check |
| `fdcpa` | FDCPA | Collection communication review queue, debt content tagging |
| `sox` | SOX | Financial reporting attestation, audit logging |
| `pci_dss` | PCI-DSS | Cardholder data blocking, payment content redaction |
| `ferpa` | FERPA | Student record filtering, education data authorization |
| `glba` | GLBA | NPI filtering, financial data authorization |

### Obligation Types

Executed in strict order: filter (1) -> audit (2) -> attestation (3) -> review (4).

| Type | Behavior |
|------|----------|
| `filter.fields` | Redact/remove sensitive fields from messages |
| `audit.log` | Write immutable audit record |
| `audit.break_glass` | Capture emergency justification |
| `audit.tag` | Attach classification/risk tags |
| `require.attestation` | Block until user explicitly attests (24h TTL) |
| `review.queue` | Block and queue for supervisor approval |

### Fail Modes

| Variable | Value | Behavior |
|----------|-------|----------|
| `policy_engine_fail_mode` | `closed` (default) | Any OPA error or obligation failure blocks the request |
| `policy_engine_fail_mode` | `log_only` | Allow through but log violations (for rollout observation) |

---

## 17. External Data Connectors

Query external databases and APIs from chat with team-based access control. Part of the Governance Hub.

### Supported Types

| Type | Driver | Example |
|------|--------|---------|
| `postgresql` | asyncpg | Company CRM, ERP databases |
| `mysql` | aiomysql | Legacy systems, WordPress |
| `mssql` | pymssql | Microsoft SQL Server |
| `rest_api` | httpx | Internal APIs, ticketing systems |

### Access Control Model

| Field | Description |
|-------|-------------|
| `grant_type` | `team` (SSO group), `user` (individual), `role` (`*` for all) |
| `permission` | `read` (SELECT only), `write` (all SQL), `admin` (manage connector) |
| `row_filter` | SQL WHERE clause injected into every query |
| `field_mask` | Allowed/denied field lists applied to results |
| `expires_at` | Optional TTL for temporary access |

Write operations are blocked for read-only grants. Results capped at 1000 rows. All queries logged to the audit chain.

---

## 18. Cloud-Init ISO Creation

The Hyper-V deployment path requires a cloud-init ISO to provision the Ubuntu VM. The `scripts/New-CloudInitIso.ps1` script creates this ISO using a three-tier fallback:

| Priority | Method | Dependency |
|----------|--------|------------|
| 1 | `oscdimg.exe` | Windows ADK |
| 2 | WSL `genisoimage` | WSL + Ubuntu distro |
| 3 | **PowerShell native** | **None** |

The PowerShell native fallback writes a minimal ISO 9660 image using .NET `System.IO.BinaryWriter`. This means Hyper-V deployments work on bare Windows Server without WSL or ADK installed.

`SetupInstall.ps1` (Step 5) attempts to install `genisoimage` in WSL if available, and warns if no ISO tool is found. The native fallback ensures `terraform apply` succeeds regardless.

---

## Appendix: Quick Reference

### Key Terraform Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `anthropic_api_key` | *(required)* | Anthropic API key |
| `sso_provider` | `none` | `azure_ad`, `okta`, or `none` |
| `litellm_global_max_budget` | `100` | Global monthly cap (USD) |
| `litellm_default_user_budget` | `5.0` | Per-user daily cap (USD) |
| `litellm_default_user_rpm` | `30` | Requests per minute per user |
| `litellm_default_user_tpm` | `100000` | Tokens per minute per user |
| `dlp_enable` | `true` | Enable DLP gateway callback |
| `dlp_block_ssn` | `true` | Block SSNs |
| `dlp_block_credit_cards` | `true` | Block credit card numbers |
| `dlp_block_phi` | `true` | Block PHI (HIPAA) |
| `dlp_block_credentials` | `true` | Block API keys, passwords |
| `dlp_custom_patterns` | `{}` | Organization-specific regex |
| `docforge_enable` | `true` | Enable DocForge file service |
| `industry` | `general` | Industry for keyword templates |
| `governance_tier` | `tier3` | Governance strictness level |
| `ops_watchtower_enable` | `true` | Auto-patch containers |
| `ops_grafana_enable` | `true` | Compliance dashboards |
| `governance_hub_enable` | `false` | Enterprise governance hub |
| `policy_engine_enable` | `false` | OPA policy enforcement |
| `policy_engine_industry_policies` | `[]` | Industry policies to load |
| `ad_domain_join` | `false` | Join VM to Active Directory |
| `keyword_categories` | `{}` | Custom keyword analysis categories |
| `log_retention_days` | `365` | Audit trail retention period |
| `ops_backup_schedule` | `daily` | PostgreSQL backup frequency |

### Post-Deployment URLs

| Service | URL | Purpose |
|---------|-----|---------|
| Admin Hub | `https://<vm-ip>/admin` | Interactive command center |
| Chat Interface | `https://<vm-ip>/` | End-user chat with Claude |
| LiteLLM Admin | `https://<vm-ip>/litellm/ui/chat` | Admin dashboard |
| LiteLLM API | `https://<vm-ip>/v1/` | OpenAI-compatible endpoint |
| Grafana | `https://<vm-ip>/grafana/` | Compliance & fleet dashboards |
| Governance Hub | `https://<vm-ip>/governance/` | Change management, sync, advisor API |
| DocForge | `https://<vm-ip>/docforge/api/formats` | File generation & conversion |
| Uptime Kuma | `https://<vm-ip>/status/` | Service health monitoring |
| Netdata | `https://<vm-ip>/netdata/` | Infrastructure monitoring |
| SSH | `ssh insidellm-admin@<vm-ip>` | VM administration |

### Claude Code CLI Setup

```bash
export ANTHROPIC_BASE_URL=http://<vm-ip>:4000
export ANTHROPIC_AUTH_TOKEN=<your-litellm-key>
```

```powershell
# PowerShell
$env:ANTHROPIC_BASE_URL = "http://<vm-ip>:4000"
$env:ANTHROPIC_AUTH_TOKEN = "<your-litellm-key>"
```

---

## License

This project is licensed under the [Business Source License 1.1](LICENSE).

**What this means:**

- **Self-hosting for your own organization:** Always permitted, no restrictions
- **Modifying and forking:** Permitted
- **Offering InsideLLM as a competing commercial product, managed service, or hosted platform:** Requires a commercial license from Uniformedi LLC
- **On April 11, 2030:** This version automatically converts to Apache License 2.0

For commercial licensing inquiries, contact: licensing@uniformedi.com

Copyright (c) 2026 Uniformedi LLC

The Humility alignment policy implements the **SAIVAS** (Sentient AI Value Alignment Standard)
framework, originally published in [*Uniform Gnosis, Volume I*](https://uniformgnosis.com/Uniform_Gnosis_Volume_I)
by Dan Medina. Copyright (c) 2026 Dan Medina. All rights reserved.

Source code: [https://github.com/Uniformedi/InsideLLM](https://github.com/Uniformedi/InsideLLM)
