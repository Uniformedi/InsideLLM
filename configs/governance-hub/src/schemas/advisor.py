from pydantic import BaseModel, Field


class AnalysisRequest(BaseModel):
    analysis_type: str = Field(
        default="comprehensive",
        pattern="^(comprehensive|cost_optimization|compliance_gaps|keyword_trends|team_utilization)$",
    )
    time_range_days: int = Field(default=30, ge=1, le=365)
    focus_areas: list[str] | None = None


class GovernanceSuggestion(BaseModel):
    title: str
    category: str
    description: str
    proposed_changes: dict
    impact_assessment: str
    priority: str  # critical, high, medium, low
    estimated_savings: str | None = None
    compliance_impact: str | None = None


class AdvisorResponse(BaseModel):
    analysis_summary: str
    suggestions: list[GovernanceSuggestion]
    data_analyzed: dict
    proposals_created: int
