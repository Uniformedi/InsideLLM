{# FDCPA §1692g(b) dispute acknowledgment / resolution letter.
   Sent after a consumer disputes a debt in writing within the 30-day window. #}

**{{ collector_legal_name }}**
{{ collector_mailing_address }}

Date: {{ issue_date }}

To: {{ consumer_name }}
{{ consumer_mailing_address }}

Reference: {{ account_reference }}
Dispute received: {{ dispute_received_date }}

---

**This is a communication from a debt collector. Any information obtained
will be used for that purpose.** {# REQUIRED_BY_FDCPA §1692e(11) #}

We are writing in response to your dispute of the debt referenced above,
which we received on {{ dispute_received_date }}.

{{ resolution_body }}

{# One of the following blocks is selected by the agent based on outcome. #}
{#
   Block A — verification obtained:
     Enclosed is verification of the debt, which includes:
       • {{ verification_item_1 }}
       • {{ verification_item_2 }}
     Collection activity had been suspended while your dispute was under
     review and may now resume.

   Block B — debt withdrawn:
     After review, we have closed the account and will cease collection
     activity. We have requested that the credit reporting agencies we
     previously reported this debt to delete the tradeline, if any.

   Block C — further information needed:
     To complete our review, we need the following additional information
     from you: {{ needed_info }}. Collection activity remains suspended
     while your dispute is pending.
#}

If you have questions, please contact us at {{ collector_phone }} between
{{ collector_hours_local }}. We cannot contact you outside those hours.

Sincerely,

{{ collector_agent_name }}
{{ collector_legal_name }}

{{ audit_footer }}
