# Attributions

InsideLLM is built on top of the open-source software, foundations, and
open standards listed below. Without these contributors, this platform
would not exist.

This document is the canonical, public-facing acknowledgment. It is
generated from the same source-of-truth as the live vendor directory in
the Governance Hub (`/governance/vendors`). When new dependencies are
added to the platform, both this document and the seeded vendor catalog
are updated together.

If your project is in the InsideLLM stack and you don't see your name
here, that's a bug — open an issue at
[Uniformedi/InsideLLM](https://github.com/Uniformedi/InsideLLM/issues)
and we'll fix it.

For the underlying philosophy — that vendors used by the platform must
contribute to FOSS or recognized standards — see
[`docs/architecture/policy-library.md`](architecture/policy-library.md)
and the seed file at
[`configs/governance-hub/src/services/vendor_seed.py`](../configs/governance-hub/src/services/vendor_seed.py).

---

## Software in the stack

Companies, foundations, and projects whose **code we run** at deploy time.

### Anthropic — frontier LLM

- **What:** Claude model family (Haiku, Sonnet, Opus). The frontier LLM behind every chat the platform serves.
- **License:** Commercial (API). Open contributions to safety research and the Model Context Protocol.
- **Contributions we credit:**
  - [Safety research and Responsible Scaling Policy](https://www.anthropic.com/research) — published transparency on model behavior.
  - [Model Context Protocol (MCP)](https://www.modelcontextprotocol.io) — open standard authored and stewarded by Anthropic.
  - [Public bug-bounty program](https://hackerone.com/anthropic) — coordinated disclosure channel.

### PostgreSQL Global Development Group — relational database

- **What:** PostgreSQL, the relational database backing LiteLLM, Open WebUI, and the Governance Hub.
- **License:** [PostgreSQL License](https://www.postgresql.org/about/licence/) (OSI-approved permissive, BSD-style).
- **Source:** [github.com/postgres/postgres](https://github.com/postgres/postgres)

### Valkey (community fork of Redis) — in-memory cache

- **What:** Cache + rate-limit state store. Currently the Redis 7.x line; the project is migrating to Valkey under the Linux Foundation following Redis Inc.'s license change.
- **License:** [BSD 3-Clause](https://github.com/valkey-io/valkey/blob/unstable/COPYING).
- **Source:** [github.com/valkey-io/valkey](https://github.com/valkey-io/valkey).
- **Steward:** [Linux Foundation](https://www.linuxfoundation.org/projects/valkey).

### F5 / NGINX — web server and reverse proxy

- **What:** TLS terminator and reverse proxy in front of every InsideLLM service.
- **License:** [BSD 2-Clause](https://nginx.org/LICENSE) (open-source NGINX).
- **Source:** [nginx.org](https://nginx.org)

### Open Policy Agent (CNCF graduated, maintainers at Apple) — policy engine

- **What:** OPA, the policy engine for Humility + industry overlays.
- **License:** [Apache 2.0](https://github.com/open-policy-agent/opa/blob/main/LICENSE).
- **Source:** [github.com/open-policy-agent/opa](https://github.com/open-policy-agent/opa).
- **Stewardship note:** Maintainers transitioned from Styra to Apple in 2026. Project remains [CNCF graduated](https://www.cncf.io/projects/open-policy-agent-opa/) with monthly release cadence intact.

### Grafana Labs — observability

- **What:** Grafana, Loki, Promtail, Tempo. Compliance dashboards, log aggregation, distributed tracing.
- **License:** [AGPL-3.0](https://github.com/grafana/grafana/blob/main/LICENSE) (Grafana core).
- **Source:** [github.com/grafana](https://github.com/grafana)
- **Engineering investment:** Employs full-time engineers across Grafana, Loki, Mimir, Tempo, and Pyroscope.

### Open WebUI — chat frontend

- **What:** The chat interface employees see. Active community-driven project.
- **License:** [MIT-derived](https://github.com/open-webui/open-webui/blob/main/LICENSE) (with branding restrictions).
- **Source:** [github.com/open-webui/open-webui](https://github.com/open-webui/open-webui)

### BerriAI / LiteLLM — model gateway

- **What:** The gateway that DLP, Humility, OPA, and budget enforcement plug into. Without LiteLLM there is no platform.
- **License:** [MIT](https://github.com/BerriAI/litellm/blob/main/LICENSE).
- **Source:** [github.com/BerriAI/litellm](https://github.com/BerriAI/litellm)

### Docker, Inc. (Moby) — container runtime

- **What:** Container runtime + Compose. Packaging and orchestration foundation for every service.
- **License:** [Apache 2.0](https://github.com/moby/moby/blob/master/LICENSE) (Moby / Docker Engine).
- **Source:** [github.com/moby/moby](https://github.com/moby/moby)
- **Standards work:** Founding member of the [Open Container Initiative](https://opencontainers.org).

### Canonical / Ubuntu — operating system

- **What:** The Linux distribution every InsideLLM VM boots from.
- **License:** Ubuntu archive — predominantly GPL/LGPL/MIT/BSD per package.
- **Source:** [launchpad.net/ubuntu](https://launchpad.net/ubuntu)
- **Engineering investment:** Employs full-time engineers across the kernel, GNOME, MicroK8s, snapd, cloud-init, and many other upstream projects.

### OpenSSL Software Foundation — cryptographic library

- **What:** The library every TLS handshake in the platform runs through.
- **License:** [Apache 2.0](https://www.openssl.org/source/license.html) (OpenSSL 3.0+).
- **Source:** [github.com/openssl/openssl](https://github.com/openssl/openssl)

### Python Software Foundation — language

- **What:** Python — Governance Hub, LiteLLM callbacks, Open WebUI, DLP and Humility code.
- **License:** [PSF License 2.0](https://docs.python.org/3/license.html) (OSI-approved, BSD-style).
- **Source:** [github.com/python/cpython](https://github.com/python/cpython)

### Uniformedi LLC — platform maintainer

- **What:** Maintainer of InsideLLM and the SAIVAS / Humility framework.
- **License:** [`humility-guardrail` is MIT](https://github.com/uniformedi/humility-guardrail/blob/main/LICENSE). InsideLLM platform itself is BSL 1.1.
- **Source:** [github.com/Uniformedi](https://github.com/Uniformedi)

---

## Standards & protocols

Bodies and consortia whose **specifications we conform to** even when no
single piece of software ships under their name.

### Internet Engineering Task Force (IETF)

The protocols that move every request through the platform:

- **HTTP/1.1** — [RFC 9112](https://datatracker.ietf.org/doc/html/rfc9112)
- **HTTP/2** — [RFC 9113](https://datatracker.ietf.org/doc/html/rfc9113)
- **HTTP/3** — [RFC 9114](https://datatracker.ietf.org/doc/html/rfc9114)
- **TLS 1.3** — [RFC 8446](https://datatracker.ietf.org/doc/html/rfc8446)
- **OAuth 2.0** — [RFC 6749](https://datatracker.ietf.org/doc/html/rfc6749) and the JOSE family ([RFC 7515](https://datatracker.ietf.org/doc/html/rfc7515) → [7519 JWT](https://datatracker.ietf.org/doc/html/rfc7519))
- **DNS** — [RFC 1034/1035](https://datatracker.ietf.org/doc/html/rfc1035) and successors
- **SMTP, IMAP, NTP**, and dozens of others

[ietf.org](https://www.ietf.org)

### Internet Assigned Numbers Authority (IANA)

Allocates and registers the protocol parameters every network call resolves
against: port numbers, MIME types, the DNS root zone, IP address space.
[iana.org](https://www.iana.org)

### World Wide Web Consortium (W3C)

HTML, CSS, WCAG, and the web APIs every InsideLLM admin page renders against.
[w3.org](https://www.w3.org)

### Open Container Initiative (OCI)

Image and runtime specifications that make the docker images we build
portable across Docker, Podman, containerd, and any other OCI runtime.
[opencontainers.org](https://opencontainers.org)

### Cloud Native Computing Foundation (CNCF)

Neutral home for OPA (graduated), Prometheus, and the broader cloud-native
ecosystem the platform is built on. [cncf.io](https://www.cncf.io)

### The Linux Foundation

Funds and hosts the Linux kernel, CNCF, [OpenSSF](https://openssf.org)
(supply-chain security: Sigstore, Scorecard, S2C2F), Valkey, and many
others. [linuxfoundation.org](https://www.linuxfoundation.org)

### Anthropic — Model Context Protocol

Anthropic also stewards an open standard that's relevant to AI integrations:
**[Model Context Protocol](https://www.modelcontextprotocol.io)**.

### NIST — for the compliance overlays

InsideLLM's industry policy overlays (HIPAA, SOX, GLBA, FERPA, FDCPA,
PCI-DSS) reference NIST guidance, especially [NIST SP 800-53](https://csrc.nist.gov/projects/risk-management/sp800-53-controls/release-search)
(security and privacy controls) and [NIST AI Risk Management Framework](https://www.nist.gov/itl/ai-risk-management-framework).
[nist.gov](https://www.nist.gov)

---

## How to add or correct an entry

The canonical source is
[`configs/governance-hub/src/services/vendor_seed.py`](../configs/governance-hub/src/services/vendor_seed.py).
Each entry has:

- **slug, name, category** — identifies the vendor / body
- **website_url** — where to verify
- **description** — what they do for the platform
- **contributions** — list of `(type_code, evidence_url, evidence_description)`
  tuples. `type_code` is one of:

| Type code | Meaning | Counts as |
|---|---|---|
| `OSS_PROJECT` | Maintains an open-source project | Software |
| `PERMISSIVE_LICENSE` | Releases own work under MIT/Apache/BSD | Software |
| `EMPLOYS_MAINTAINERS` | Employs OSS maintainers full-time | Software |
| `BUG_BOUNTY` | Runs a public bug-bounty | Software (security posture) |
| `STANDARDS_BODY` | Active in a recognized standards body | Standards/Protocols |
| `FOUNDATION_SPONSOR` | Sponsors an open-source foundation | Standards/Protocols |
| `TRANSPARENCY_PUBLICATION` | Publishes substantive technical research | Either |

Add or edit the seed, run the platform once (the seed function is
idempotent — only inserts missing slugs), then update this document to
match. Send a PR to
[Uniformedi/InsideLLM](https://github.com/Uniformedi/InsideLLM).

---

## License notice

This document and the underlying seed file are licensed under the same
terms as the InsideLLM repository (BSL 1.1). The list of vendors and
their contributions is editorial — inclusion is not endorsement and
exclusion is not criticism, just a reflection of what the platform
currently runs on top of.
