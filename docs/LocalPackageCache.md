# Local Package Cache

When deploying more than one InsideLLM VM, you can cut ~15–20 minutes off
every post-first VM's provisioning by pointing new VMs at a local apt and
Docker image mirror that runs on the **fleet primary**. No upstream
traffic for packages / images that have already been cached.

---

## How it works

The fleet primary (VM with `vm_role = "primary"`) auto-runs two extra
containers in its Docker Compose stack:

| Container | Port | Role |
|---|---|---|
| `insidellm-apt-cacher` | `3142` | `apt-cacher-ng` — transparent apt proxy |
| `insidellm-registry-mirror` | `5000` | `registry:2` — pull-through Docker Hub mirror |

Every other VM's cloud-init reads two Terraform vars and plumbs them in
before any package or image download runs:

| tfvar | Cloud-init effect |
|---|---|
| `apt_mirror_host` | Adds `http_proxy` / `https_proxy` to `apt` config. |
| `docker_mirror_host` | Writes `registry-mirrors` + `insecure-registries` into `/etc/docker/daemon.json` before Docker starts. |

Empty values (defaults) preserve the previous direct-to-upstream behavior.

---

## Enablement

### Primary (one-time)
```hcl
# terraform.tfvars
vm_role = "primary"
```
That's it — `pkg_mirror_enable` is derived as `true` when `vm_role=primary`.
If you want the mirror on a different VM (e.g., a dedicated storage node),
set `pkg_mirror_enable = true` explicitly.

After deploy, the primary's READY banner shows:
```
Local package mirrors (point future VMs here to skip upstream traffic):
  apt proxy:        http://192.168.100.10:3142
  Docker registry:  http://192.168.100.10:5000
```

### Every other VM
```hcl
# terraform.tfvars (gateway / workstation / edge / voice)
apt_mirror_host    = "192.168.100.10"
docker_mirror_host = "192.168.100.10"
```

`fleet.yaml` can set these in the `shared:` block once so every peer VM
inherits them automatically.

---

## What's cached vs. what isn't

**Cached (transparent):**
- Every `apt-get update` + `apt-get install` call
- Every Docker Hub `docker pull`

**Not cached (yet):**
- `ghcr.io` and `quay.io` images (Guacamole OAuth2 Proxy, etc.)
- Python wheels from pypi.org (humility-guardrail install)
- Raw downloads from apache.org / github.com (Guacamole LDAP JAR)

These combine to ~150 MB per VM and aren't the bottleneck. They can be
added later if needed.

---

## Cache location + disk usage

On the primary:

```
/opt/InsideLLM/data/apt-cache/       # ~1.5 GB after warming
/opt/InsideLLM/data/registry/        # ~4 GB after warming
```

Total ~5–6 GB. Both volumes are bind-mounted so rebuilds of the primary's
Compose stack preserve cached packages.

---

## Freshness

Both proxies revalidate on each request with conditional HTTP
(`If-Modified-Since` / ETag). "Get the latest" still works — you just pay
a ~2-second freshness check rather than a full redownload when upstream
hasn't changed.

**Beware `:latest` Docker tags.** They move silently and the registry
mirror will serve a stale layer list for up to 5 minutes. InsideLLM's
compose pins every image to a specific version; do not revert to
`:latest` in production.

---

## Operational tasks

### Warm the cache manually (optional)
After primary is up, run on the primary VM:

```bash
# Prime apt cache
for pkg in docker-ce docker-compose-plugin postgresql-client; do
    apt-get install --download-only -y $pkg
done

# Prime Docker images
for img in \
    postgres:16-alpine redis:7-alpine nginx:1.27-alpine \
    ghcr.io/berriai/litellm:v1.76.0-stable \
    ghcr.io/open-webui/open-webui:main \
    grafana/grafana-oss:11.3.0 \
    grafana/loki:3.2.0 \
    grafana/promtail:3.2.0 ; do
    docker pull "$img"
done
```

Alternatively, just deploy the first gateway — it warms the cache as
a side effect.

### Check cache size
```bash
ssh insidellm-admin@<primary>
sudo du -sh /opt/InsideLLM/data/apt-cache /opt/InsideLLM/data/registry
```

### Clear cache (rare)
```bash
# Stop containers, wipe, restart
sudo docker stop insidellm-apt-cacher insidellm-registry-mirror
sudo rm -rf /opt/InsideLLM/data/apt-cache/* /opt/InsideLLM/data/registry/*
sudo docker start insidellm-apt-cacher insidellm-registry-mirror
```

Only do this if you suspect a poisoned cache; normal operation never
requires manual cleanup.

---

## Security posture

- The mirrors listen on the primary's VLAN-facing IP (`fleet_primary_host`).
- No authentication — assumption is that the InsideLLM VLAN is trusted. If
  you want auth, front the containers with nginx basic-auth or add them to
  the edge's `auth_request` chain.
- `apt-cacher-ng` + `registry:2` are widely deployed, well-audited open-source
  projects. No custom code involved.
- HTTPS is terminated at the proxies; upstream connections use TLS as
  normal. Packages are verified by apt's own signature chain regardless of
  proxy (GPG signatures are checked per-package).

---

## Expected speedups

Measured on a Dell Precision 7920 host, 1 Gbps internet:

| Step | Without mirror | With warmed mirror | Savings |
|---|---|---|---|
| `apt-get update && apt-get install task-xfce-desktop sssd realmd xrdp (…)` | ~12 min | ~90 s | ~10 min |
| `docker pull` of full Compose stack (~4 GB) | ~8 min | ~45 s | ~7 min |
| **Total per 2nd+ VM deploy** | ~25 min | ~5 min | **~20 min** |

Expect a proportional bandwidth reduction on the host's internet link.

---

## Rollback

If the mirrors misbehave for any reason, set on each VM's tfvars:

```hcl
apt_mirror_host    = ""
docker_mirror_host = ""
```

Redeploy (or manually `rm /etc/apt/apt.conf.d/*proxy*` + edit
`/etc/docker/daemon.json` + `systemctl restart docker`). VMs fall straight
back to upstream.
