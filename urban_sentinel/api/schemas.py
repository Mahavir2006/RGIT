from __future__ import annotations

from pydantic import BaseModel, Field

from urban_sentinel.domain.models import ProcessedWorkflowInput, ReviewDecision


class AnalyzeRequest(BaseModel):
    payload: ProcessedWorkflowInput | None = None
    material_change: bool = True
    reanalysis_scope: list[str] = Field(default_factory=lambda: ["ALL"])
    wait: bool = False


class AnalyzeResponse(BaseModel):
    workflow_id: str
    status: str


class ReviewRequest(BaseModel):
    decision: ReviewDecision
    target_id: str | None = None
    notes: str | None = None
    actor: str = "operator"


class DepartmentReportRouteRequest(BaseModel):
    department_id: str


class DepartmentReportSubmitRequest(BaseModel):
    confirm: bool
