{# §1692c(c) cease-and-desist acknowledgment. Sent after the consumer has
   notified in writing that they wish us to cease communications. Records
   the request and confirms the scope of permitted future contact. #}

**{{ collector_legal_name }}**
{{ collector_mailing_address }}

Date: {{ issue_date }}

To: {{ consumer_name }}
{{ consumer_mailing_address }}

Reference: {{ account_reference }}

---

**This is a communication from a debt collector. Any information obtained
will be used for that purpose.** {# REQUIRED_BY_FDCPA §1692e(11) #}

Dear {{ consumer_salutation }},

We received your written request dated {{ cease_request_date }}, in
which you asked that we cease further communications about the debt
referenced above. This letter confirms our receipt of that request and
is itself one of the three notices permitted under 15 USC §1692c(c).

**What this means going forward:**

- We will not contact you further about this debt, except as
  specifically permitted by §1692c(c):
  {# REQUIRED_BY_FDCPA §1692c(c) — three permitted notices #}
  1. to advise you that our further efforts are being terminated;
  2. to notify you that we or the creditor may invoke specific
     remedies which we ordinarily invoke; or
  3. to notify you that we or the creditor intend to invoke a
     specific remedy.
- Collection activity on the underlying debt may continue through
  other permitted means and does not lapse because we have ceased
  communications.
- If the debt is subsequently transferred to another collector or
  returned to the creditor, that party is not automatically bound by
  this request. You may wish to send the same written notice to any
  future holder of this debt.

**If you did not send this request,** or if you believe this letter
was sent in error, please contact us immediately at {{ collector_phone }}
between {{ collector_hours_local }}, or mail a written notice to the
address above. Until we receive such a notice from you, we will
continue to honor the cease request.

**Your rights under federal law** include the right to request
validation of the debt (§1692g), to dispute the debt in writing within
the validation window, and to consult an attorney. This letter does
not waive any of those rights.

{# State-specific disclosures appear below when state overlay is active. #}
{{ state_disclosures_block }}

---

Sincerely,

{{ collector_agent_name }}
{{ collector_legal_name }}

{{ audit_footer }}
