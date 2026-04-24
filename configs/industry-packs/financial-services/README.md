# Financial Services — Industry Pack (scaffolded)

**Status: scaffolded (0.1.0).** Manifest only. Agents, DLP patterns, and
document templates ship in 0.2.0.

This pack demonstrates that the Industry Pack pattern applies to another
heavily-regulated vertical. The regulatory scaffolding is already shipped:

- Guardrail profile: `configs/opa/policies/profiles/tier_financial_regulated.rego`
- Industry overlays: `configs/opa/policies/industry/{sox,pci_dss,glba}.rego`
- Humility base: `configs/opa/policies/humility/base.rego`

Follow the [Collections](../collections/README.md) pack as the worked
example when filling in agents, templates, DLP patterns, and the Humility
overlay. Authoring guide in [../README.md](../README.md).
