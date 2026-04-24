# Healthcare — Industry Pack (scaffolded)

**Status: scaffolded (0.1.0).** Manifest only. Agents, DLP patterns, and
document templates ship in 0.2.0.

This pack exists to prove the Industry Pack pattern scales beyond the
[Collections](../collections/README.md) reference implementation. The
regulatory scaffolding is already shipped in the platform:

- Guardrail profile: `configs/opa/policies/profiles/tier_hipaa_regulated.rego`
- Industry overlay: `configs/opa/policies/industry/hipaa.rego`
- Humility base (never disabled): `configs/opa/policies/humility/base.rego`

The Collections pack is the worked example; follow its structure for each
layer (agents, DLP, documents, prompts). See [../README.md](../README.md)
for the authoring guide.
