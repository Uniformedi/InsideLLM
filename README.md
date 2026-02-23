# Inside LLM — Architecture & Product Use Case

**Version:** 1.0 | **Author:** Dan Medina, Uniformedi LLC | **Date:** February 2026

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
8. [Identity & Access Management](#8-identity--access-management)
9. [Security Architecture](#9-security-architecture)
10. [Cost Governance & Rate Limiting](#10-cost-governance--rate-limiting)
11. [Deployment & Operations](#11-deployment--operations)
12. [Product Use Case](#12-product-use-case)

---

## 1. Executive Summary

The Inside LLM is a **self-hosted, on-premises AI gateway** that provides
enterprise-grade access to Anthropic's Claude models. A single `terraform apply`
deploys a fully configured Ubuntu VM on Windows Hyper-V, running five containerized
services that deliver:

- **Chat interface** for non-technical users (Open WebUI)
- **API gateway** for developers and CLI tools (LiteLLM)
- **Data Loss Prevention** scanning on every message and uploaded file (custom pipeline)
- **Document Q&A (RAG)** with local embeddings — upload files and ask questions against them
- **SSO integration** with Azure AD or Okta (OIDC)
- **Per-user budgets and rate limits** with real-time enforcement
- **Full audit trail** of every API call

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
                         |          Windows Hyper-V Host                 |
                         |          (Windows 11 Pro / Server)            |
                         |                                              |
                         |  +----------------------------------------+  |
                         |  |         Ubuntu 24.04 LTS VM             |  |
                         |  |         4 vCPU | 8 GB RAM | 80 GB      |  |
                         |  |                                         |  |
+----------+ HTTPS 443   |  |  +-----------------------------------+  |  |
|          |-------------+--+->|          Nginx 1.27                |  |  |
|  Users   |             |  |  |   TLS 1.2/1.3 Termination         |  |  |
| (Browser)|             |  |  |   HSTS | Security Headers         |  |  |
+----------+             |  |  +-----+----------+----------+-------+  |  |
                         |  |        |          |          |          |  |
+----------+ HTTPS 443   |  |   /    |    /v1/  |  /litellm/         |  |
|  Claude  |-------------+--+->      |          |          |          |  |
|  Code    |             |  |        v          v          v          |  |
|  CLI     |             |  |  +-----------+  +------------+         |  |
+----------+             |  |  | Open      |  | LiteLLM    |         |  |
                         |  |  | WebUI     |  | Proxy      |<--+     |  |
                         |  |  | :8080     |  | :4000      |   |     |  |
                         |  |  +-----+-----+  +------+-----+   |     |  |
                         |  |        |               |          |     |  |
                         |  |   DLP Pipeline    Budget/Rate     |     |  |
                         |  |   (inlet/outlet)  Enforcement     |     |  |
                         |  |        |               |          |     |  |
                         |  |        +-------+-------+          |     |  |
                         |  |                |                  |     |  |
                         |  |                v                  |     |  |
                         |  |  +-------------+  +----------+   |     |  |
                         |  |  | PostgreSQL  |  | Redis    |---+     |  |
                         |  |  | 16-alpine   |  | 7-alpine |         |  |
                         |  |  | Users,Spend |  | Rate     |         |  |
                         |  |  | Audit,Teams |  | Limits   |         |  |
                         |  |  +-------------+  +----------+         |  |
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
Docker Bridge Network: claude-internal (172.28.0.0/16)
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
          +------+-------+
          | Open WebUI   |
          | :8080        |
          +------+-------+
                 |
          +------+-------+
          |   Nginx      |
          |  :80  :443   |  <--------  External Users
          +--------------+

Exposed Host Ports:
  80   -> Nginx   (HTTP redirect to HTTPS)
  443  -> Nginx   (HTTPS -- primary entry point)
  4000 -> LiteLLM (direct API access)
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
  | Open WebUI       |
  | DLP Pipeline     |---- INLET: Scan message text + uploaded files
  | (pre-processing) |     - Excel, CSV, PDF, Word, PPTX scanned
  |                  |     - SSN? BLOCK
  |                  |     - Credit card? BLOCK
  |                  |     - PHI? BLOCK
  |                  |     - API keys? BLOCK
  |                  |     - Custom patterns? BLOCK
  +--------+---------+
           | Message + clean files pass DLP
           v
  +------------------+
  | LiteLLM Proxy    |  1. Authenticate user (SSO token / API key)
  |                  |  2. Check budget (PostgreSQL: $5/day remaining?)
  |                  |  3. Check rate limit (Redis: 30 RPM / 100K TPM?)
  |                  |  4. Check cache (Redis: seen this prompt before?)
  |                  |  5. Route to correct Claude model
  +--------+---------+
           |
           v
  +------------------+
  | Anthropic API    |  Claude generates response
  +--------+---------+
           |
           v
  +------------------+
  | LiteLLM Proxy    |  6. Record token usage + cost in PostgreSQL
  |                  |  7. Log to Langfuse (audit trail)
  |                  |  8. Update Redis rate limit counters
  +--------+---------+
           |
           v
  +------------------+
  | Open WebUI       |
  | DLP Pipeline     |---- OUTLET: Scan assistant response
  | (post-processing)|     - Redact any echoed-back PII/PHI/creds
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
| **Reverse Proxy** | [Nginx](https://nginx.org/) | BSD-2 | 1.27 | TLS termination, HTTPS routing, security headers |
| **Database** | [PostgreSQL](https://www.postgresql.org/) | PostgreSQL | 16 | User data, spend tracking, team budgets, audit logs |
| **Cache** | [Redis](https://redis.io/) | BSD-3 | 7 | Rate limit counters, response cache, session data |
| **Containers** | [Docker](https://www.docker.com/) + [Compose](https://docs.docker.com/compose/) | Apache 2.0 | CE | Container orchestration, networking, health checks |
| **IaC** | [Terraform](https://www.terraform.io/) | BSL 1.1 | >= 1.5 | Infrastructure provisioning, config templating |
| **Provisioning** | [cloud-init](https://cloudinit.readthedocs.io/) | Apache 2.0 | default | First-boot VM automation |
| **Hypervisor** | [Hyper-V](https://learn.microsoft.com/en-us/virtualization/hyper-v-on-windows/) | Windows | Win 11 Pro | Virtual machine hosting (included in Windows Pro/Enterprise) |
| **Audit** | [Langfuse](https://langfuse.com/) | MIT | callback | LLM observability, prompt logging, cost tracking |
| **Guest OS** | [Ubuntu](https://ubuntu.com/) | FOSS | 24.04 LTS | Server operating system |

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
|              - Response caching reduces API costs                |
|                                                                  |
| Nginx        - Industry standard for TLS termination             |
|              - WebSocket support (streaming responses)           |
|                                                                  |
| Hyper-V      - Built into Windows Pro/Enterprise (no cost)       |
|              - IT departments already have Hyper-V expertise     |
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
|  | Ubuntu 24.04 LTS VM                        |  |
|  |   - Gen 2 (UEFI + Secure Boot)            |  |
|  |   - 4 vCPU, 8 GB RAM, 80 GB disk          |  |
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

- **Volume:** `/opt/claude-wrapper/data/postgres` (persistent across restarts)
- **Health check:** `pg_isready -U litellm` every 10s
- **Not exposed** to host network -- internal access only

### Redis 7

**Role:** High-speed cache and rate limiter.

| Data Stored | Purpose |
|-------------|---------|
| Rate limit counters | Requests-per-minute (RPM) and tokens-per-minute (TPM) per user |
| Response cache | Deduplicate identical prompts (cost savings) |
| Session data | Temporary session state |

- **Memory:** Capped at 256 MB with LRU eviction
- **Volume:** `/opt/claude-wrapper/data/redis` (persistence for cache warmth)
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
- **Pipeline system** -- hosts the DLP filter that scans messages and uploaded files
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
+------------------+             | /nginx-health -> 200 OK          |
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

The DLP system is implemented as an **Open WebUI Filter Pipeline** (v2.0) -- a
Python module that intercepts every message and uploaded file at two critical
points in the conversation flow. It is the primary compliance control in the stack.

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

The DLP pipeline runs **before** Open WebUI's RAG pipeline, meaning files are
scanned at the raw content level before any text extraction or embedding occurs.
If a file contains sensitive data, it is blocked before the LLM ever sees it.

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

DLP is configurable at **two levels**:

**1. Terraform Variables (deploy-time)**

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

**2. Open WebUI Admin Panel (runtime)**

Navigate to **Admin > Pipelines > DLP Filter > Valves**:

| Setting | Default | Description |
|---------|---------|-------------|
| `enabled` | `true` | Master on/off |
| `mode` | `block` | `block` or `redact` |
| `block_ssn` | `true` | SSN detection |
| `block_credit_cards` | `true` | Credit card detection |
| `block_phi` | `true` | PHI detection |
| `block_credentials` | `true` | Secret detection |
| `block_bank_accounts` | `true` | Bank info detection |
| `block_standalone_dates` | `true` | Detect standalone date patterns (MM/DD/YYYY, YYYY-MM-DD) |
| `scan_file_uploads` | `true` | Scan uploaded files (Excel, PDF, etc.) |
| `max_file_size_mb` | `50` | Max file size to scan (larger files skipped) |
| `log_detections` | `true` | Audit logging |
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

### Auto-Registration on Deployment

The DLP pipeline is **automatically registered** as a global filter function in
Open WebUI during the post-deployment step. No manual configuration is needed --
`terraform apply` handles everything:

1. Services start and pass health checks
2. `post-deploy.sh` registers the DLP pipeline as an Open WebUI Function
3. The function is activated globally (applies to all users and models)
4. On subsequent deploys, the function is updated in-place (idempotent)

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

The DLP pipeline and RAG system work together in sequence:

1. **DLP scans first** -- uploaded files are checked for sensitive data before processing
2. **RAG processes clean files** -- only files that pass DLP are embedded and stored
3. **Full context injection** -- Claude receives the complete file content alongside the user's question
4. **DLP scans the response** -- the outlet filter checks Claude's response for any echoed-back PII

If a file contains sensitive data (SSNs, credit cards, PHI), the DLP filter blocks the
entire request before RAG or Claude ever see the file contents.

---

## 8. Identity & Access Management

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
 |     Azure AD Tenant       |         |     Claude Wrapper        |
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
2. Set Redirect URI to `https://<vm-ip>/litellm/sso/callback`
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
 |     Okta Tenant           |         |     Claude Wrapper        |
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
3. Set Sign-in redirect URI to `https://<vm-ip>/litellm/sso/callback`
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

LAYER 6: Data Protection (DLP)
+------------------------------------------------------------+
| DLP pipeline: PII, PHI, credentials blocked/redacted      |
| Inlet scanning (messages + uploaded files)                |
| Outlet scanning (assistant responses + RAG excerpts)      |
| Custom patterns for org-specific data                     |
+------------------------------------------------------------+

LAYER 7: Cost Protection
+------------------------------------------------------------+
| Per-user daily budgets ($5/day default)                    |
| Global monthly cap ($100/month default)                   |
| Rate limiting: 30 RPM / 100K TPM per user                |
| 80% budget alert via Slack                                |
+------------------------------------------------------------+

LAYER 8: Audit & Observability
+------------------------------------------------------------+
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

### Prerequisites

| Requirement | Details |
|-------------|---------|
| Windows 11 Pro or Server 2022+ | Hyper-V capable |
| 16 GB+ host RAM | 8 GB for VM + headroom |
| 100 GB+ free disk | VM disk + images |
| Terraform >= 1.5 | IaC tool |
| WSL2 | For genisoimage (cloud-init ISO creation) |
| Anthropic API key | From console.anthropic.com |

### One-Command Deployment

```powershell
# 1. Run prerequisites (once, requires admin)
.\Setup-Prerequisites.ps1

# 2. Configure
cp terraform.tfvars.example terraform.tfvars
# Edit terraform.tfvars with your settings

# 3. Deploy
terraform init
terraform plan -out=tfplan
terraform apply tfplan
```

### Auto-Start on Boot

The stack is configured as a **systemd service** on the VM:

```
 VM Boot -> systemd -> claude-wrapper.service -> docker compose up -d
```

All containers have `restart: always`, so individual container crashes
are automatically recovered.

### Health Monitoring

| Container | Health Check | Interval |
|-----------|-------------|----------|
| PostgreSQL | `pg_isready -U litellm` | 10s |
| Redis | `redis-cli ping` | 10s |
| LiteLLM | `python3 urllib > /health/liveliness` | 15s |
| Open WebUI | `curl > /health` | 15s |
| Nginx | Depends on Open WebUI health | -- |

External monitoring endpoints:
- `http://<host>/health` (Nginx HTTP)
- `https://<host>/nginx-health` (Nginx HTTPS)

### File Structure

```
InternalClaude/
+-- main.tf                             # Root module: VM + provisioning
+-- variables.tf                        # All input variables
+-- outputs.tf                          # VM IP, URLs, secrets
+-- providers.tf                        # Hyper-V provider config
+-- terraform.tfvars.example            # Template for your values
+-- Setup-Prerequisites.ps1             # Windows host preparation
+-- configs/
|   +-- cloud-init/
|   |   +-- user-data.yaml.tpl          # VM first-boot provisioning
|   |   +-- meta-data.yaml.tpl          # Cloud-init identity
|   |   +-- network-config.yaml.tpl     # Static IP / DHCP config
|   +-- litellm/
|   |   +-- config.yaml.tpl             # API gateway configuration
|   +-- nginx/
|   |   +-- nginx.conf.tpl              # Reverse proxy + TLS
|   +-- open-webui/
|       +-- dlp-pipeline.py             # DLP filter (messages + files)
+-- scripts/
    +-- docker-compose.yml.tpl          # All 5 services definition
    +-- post-deploy.sh.tpl              # Team creation, systemd setup
```

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

| Feature | Claude Wrapper | Direct API | ChatGPT Enterprise |
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
| `dlp_enable` | `true` | Enable DLP pipeline |
| `dlp_block_ssn` | `true` | Block SSNs |
| `dlp_block_credit_cards` | `true` | Block credit card numbers |
| `dlp_block_phi` | `true` | Block PHI (HIPAA) |
| `dlp_block_credentials` | `true` | Block API keys, passwords |
| `dlp_block_standalone_dates` | `true` | Block standalone date patterns (DOB) |
| `dlp_custom_patterns` | `{}` | Organization-specific regex |

### Post-Deployment URLs

| Service | URL | Purpose |
|---------|-----|---------|
| Chat Interface | `https://<vm-ip>/` | End-user chat with Claude |
| LiteLLM Admin | `https://<vm-ip>/litellm/ui` | Admin dashboard |
| LiteLLM API | `https://<vm-ip>/v1/` | OpenAI-compatible endpoint |
| SSH | `ssh claude-admin@<vm-ip>` | VM administration |

### Claude Code CLI Setup

```bash
export ANTHROPIC_BASE_URL=https://<vm-ip>/v1
export ANTHROPIC_API_KEY=<your-litellm-key>
```
