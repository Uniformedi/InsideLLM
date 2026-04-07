import json
import logging

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from ..config import settings
from ..schemas.advisor import AdvisorResponse, AnalysisRequest, GovernanceSuggestion
from ..schemas.changes import ChangeCreate
from .change_service import create_proposal
from .sync_service import collect_telemetry

logger = logging.getLogger(__name__)

ANALYSIS_PROMPT = """You are an AI Governance Advisor for an enterprise AI deployment called InsideLLM.
Your role is to analyze governance telemetry data and suggest improvements to the AI governance framework.

IMPORTANT RULES:
- You NEVER implement changes directly. All suggestions become proposals requiring supervisor approval.
- Focus on: cost optimization, compliance gaps, keyword pattern shifts, team budget utilization.
- Each suggestion must include: title, category, description, proposed_changes (as JSON), impact_assessment, priority, estimated_savings (if applicable).
- Categories: keyword, policy, budget, model, config, framework
- Priorities: critical, high, medium, low

CURRENT INSTANCE CONFIG:
- Industry: {industry}
- Governance Tier: {governance_tier}
- Data Classification: {data_classification}

TELEMETRY DATA (last {days} days):
{telemetry_json}

ANALYSIS TYPE: {analysis_type}
{focus_areas}

Respond with a JSON object containing:
{{
  "analysis_summary": "Brief overview of findings",
  "suggestions": [
    {{
      "title": "Short title",
      "category": "one of: keyword, policy, budget, model, config, framework",
      "description": "Detailed explanation",
      "proposed_changes": {{"key": "value"}},
      "impact_assessment": "What this changes and why",
      "priority": "critical|high|medium|low",
      "estimated_savings": "$X/month or null",
      "compliance_impact": "How this affects compliance posture"
    }}
  ]
}}
"""


async def run_analysis(db: AsyncSession, request: AnalysisRequest) -> AdvisorResponse:
    """Run AI governance analysis and create change proposals from suggestions."""
    telemetry = await collect_telemetry(db, days=request.time_range_days)

    focus = ""
    if request.focus_areas:
        focus = f"FOCUS AREAS: {', '.join(request.focus_areas)}"

    prompt = ANALYSIS_PROMPT.format(
        industry=settings.industry,
        governance_tier=settings.governance_tier,
        data_classification=settings.data_classification,
        days=request.time_range_days,
        telemetry_json=json.dumps(telemetry.model_dump(), indent=2, default=str),
        analysis_type=request.analysis_type,
        focus_areas=focus,
    )

    # Call LiteLLM API
    try:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(
                f"{settings.litellm_url}/v1/chat/completions",
                headers={"Authorization": f"Bearer {settings.litellm_api_key}"},
                json={
                    "model": settings.advisor_model,
                    "messages": [{"role": "user", "content": prompt}],
                    "temperature": 0.3,
                    "max_tokens": 4096,
                },
            )
            resp.raise_for_status()
            content = resp.json()["choices"][0]["message"]["content"]
    except Exception as e:
        logger.error(f"LiteLLM API call failed: {e}")
        return AdvisorResponse(
            analysis_summary=f"Analysis failed: {e}",
            suggestions=[],
            data_analyzed=telemetry.model_dump(),
            proposals_created=0,
        )

    # Parse AI response
    try:
        # Strip markdown code fences if present
        cleaned = content.strip()
        if cleaned.startswith("```"):
            cleaned = cleaned.split("\n", 1)[1]
            cleaned = cleaned.rsplit("```", 1)[0]
        parsed = json.loads(cleaned)
    except json.JSONDecodeError:
        logger.error(f"Failed to parse AI response: {content[:500]}")
        return AdvisorResponse(
            analysis_summary="AI response could not be parsed as JSON.",
            suggestions=[],
            data_analyzed=telemetry.model_dump(),
            proposals_created=0,
        )

    # Create change proposals from suggestions
    suggestions = []
    proposals_created = 0
    for s in parsed.get("suggestions", []):
        try:
            suggestion = GovernanceSuggestion(**s)
            suggestions.append(suggestion)

            # Create as pending proposal
            await create_proposal(db, ChangeCreate(
                title=suggestion.title,
                description=suggestion.description,
                category=suggestion.category,
                proposed_changes=suggestion.proposed_changes,
                impact_assessment=suggestion.impact_assessment,
                proposed_by="ai-governance-advisor",
                source="ai_advisor",
                ai_rationale=f"Priority: {suggestion.priority}. {suggestion.compliance_impact or ''}",
            ))
            proposals_created += 1
        except Exception as e:
            logger.warning(f"Failed to create proposal from suggestion: {e}")

    return AdvisorResponse(
        analysis_summary=parsed.get("analysis_summary", "Analysis complete."),
        suggestions=suggestions,
        data_analyzed=telemetry.model_dump(),
        proposals_created=proposals_created,
    )
