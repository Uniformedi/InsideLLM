{# Settlement offer letter. Ships after all §1692g validation obligations are
   satisfied and the consumer has not disputed. Discretionary and always
   routes through the approval queue before sending. #}

**{{ collector_legal_name }}**
{{ collector_mailing_address }}
{{ collector_phone }} · {{ collector_hours_local }}

Date: {{ issue_date }}

To: {{ consumer_name }}
{{ consumer_mailing_address }}

Reference: {{ account_reference }}

---

**This is a communication from a debt collector. Any information obtained
will be used for that purpose.** {# REQUIRED_BY_FDCPA §1692e(11) #}

Dear {{ consumer_salutation }},

We are writing regarding the account referenced above. The current
balance is **{{ debt_amount_usd }}**, owed to **{{ current_creditor_name }}**.

**Settlement offer**

Because we understand that full repayment may not be practical, we are
authorized to accept a one-time payment of **{{ settlement_amount_usd }}**
as full resolution of this account. This amount represents
{{ settlement_percentage }}% of the balance.

This offer is valid until **{{ settlement_expiration_date }}**. If we
receive the settlement payment by that date, we will:

- Report the account as "settled in full" to the creditor.
- Close the account in our records.
- Cease further collection activity on this debt.

**Important:**

- This offer is extended at the creditor's authorization. It does not
  constitute a waiver of any legal rights or obligations.
- Paying less than the full balance may have tax implications; we do
  not provide tax advice. A canceled-debt form (IRS Form 1099-C) may
  be issued if required by law.
- If you do not accept this offer, collection activity on the remaining
  balance may continue, within the limits set by the Fair Debt
  Collection Practices Act and applicable state law.

**How to respond:**

- To accept, call us at {{ collector_phone }} between
  {{ collector_hours_local }}, or mail payment and a signed copy of
  this letter to the address above.
- To discuss alternative arrangements, contact us at the same number.

If you prefer not to receive further communications about this debt,
you may notify us in writing to cease communications. {# §1692c(c) #}

{# State-specific disclosures appear below when state overlay is active. #}
{{ state_disclosures_block }}

---

Sincerely,

{{ collector_agent_name }}
{{ collector_legal_name }}

{# Document footer — filed into audit chain on generation. #}
{{ audit_footer }}
