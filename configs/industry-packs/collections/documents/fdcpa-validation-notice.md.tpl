{# FDCPA §1692g(a) Validation Notice — CFPB Reg F model form adapted.
   DocForge renders with {{ variable }} substitution. Fields marked
   REQUIRED_BY_FDCPA are mandatory; removing any will fail a compile-time
   check in the template engine. #}

**{{ collector_legal_name }}**
{{ collector_mailing_address }}
{{ collector_phone }} · {{ collector_hours_local }}

Date: {{ issue_date }}

To: {{ consumer_name }}
{{ consumer_mailing_address }}

Reference: {{ account_reference }}

---

**This is a communication from a debt collector. Any information obtained
will be used for that purpose.** {# REQUIRED_BY_FDCPA §1692e(11) — mini-Miranda #}

We are writing to you about a debt.

**Amount of the debt:** {{ debt_amount_usd }} {# REQUIRED_BY_FDCPA §1692g(a)(1) #}

**Creditor to whom the debt is owed:** {{ current_creditor_name }} {# REQUIRED_BY_FDCPA §1692g(a)(2) #}

**Original creditor (if different):** {{ original_creditor_name_or_blank }}

Unless you, within 30 days after receipt of this notice, dispute the
validity of the debt, or any portion of it, this debt will be assumed
to be valid by us. {# REQUIRED_BY_FDCPA §1692g(a)(3) #}

If you notify us in writing within 30 days from receipt of this notice
that the debt, or any portion of it, is disputed, we will obtain
verification of the debt or a copy of a judgment against you and mail a
copy of that verification or judgment to you. {# REQUIRED_BY_FDCPA §1692g(a)(4) #}

Upon your written request within 30 days, we will provide you with the
name and address of the original creditor, if different from the current
creditor. {# REQUIRED_BY_FDCPA §1692g(a)(5) #}

**How to respond:**

- To dispute this debt, mail a written statement to the address above, or
  email {{ disputes_email }}.
- To request verification, follow the same process.
- To make a payment, use the options at {{ payments_url_or_phone }}.

If you prefer not to receive communications about this debt, you may notify
us in writing to cease communications. {# §1692c(c) #}

{# State-specific disclosures appear below when state overlay is active. #}
{{ state_disclosures_block }}

---

Sincerely,

{{ collector_agent_name }}
{{ collector_legal_name }}

{# Document footer — filed into audit chain on generation. #}
{{ audit_footer }}
