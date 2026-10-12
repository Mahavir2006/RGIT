from __future__ import annotations

from pydantic import BaseModel, Field


class ActionCatalogueItem(BaseModel):
    action_id: str
    description: str
    cost: str
    time_to_effect: str
    feasibility: str
    expected_risk_reduction: float = Field(ge=0.0, le=1.0)
    applicable_event_types: list[str] = Field(default_factory=list)
    requires_human_approval: bool = True
    observation_first: bool = False


DEFAULT_ACTIONS: list[ActionCatalogueItem] = [
    ActionCatalogueItem(
        action_id="issue_public_advisory",
        description="Issue a localized flooding / disruption advisory to operators and the public.",
        cost="low",
        time_to_effect="minutes",
        feasibility="high",
        expected_risk_reduction=0.25,
        applicable_event_types=["weather", "water_level", "citizen_report", "traffic"],
        requires_human_approval=True,
    ),
    ActionCatalogueItem(
        action_id="request_additional_observations",
        description="Request additional water-level or CCTV observations before escalating infrastructure control.",
        cost="low",
        time_to_effect="tens of minutes",
        feasibility="high",
        expected_risk_reduction=0.1,
        applicable_event_types=["water_level", "sensor_health", "citizen_report"],
        requires_human_approval=True,
        observation_first=True,
    ),
    ActionCatalogueItem(
        action_id="traffic_diversion",
        description="Prepare a traffic diversion around waterlogged or blocked segments.",
        cost="medium",
        time_to_effect="tens of minutes",
        feasibility="medium",
        expected_risk_reduction=0.4,
        applicable_event_types=["traffic", "water_level", "citizen_report"],
        requires_human_approval=True,
    ),
    ActionCatalogueItem(
        action_id="deploy_pumps",
        description="Stage mobile pumps at confirmed waterlogged locations.",
        cost="high",
        time_to_effect="hours",
        feasibility="medium",
        expected_risk_reduction=0.55,
        applicable_event_types=["water_level", "citizen_report", "weather"],
        requires_human_approval=True,
    ),
    ActionCatalogueItem(
        action_id="protect_emergency_access",
        description="Keep emergency-access corridors clear if cascade analysis identifies hospital or depot dependency.",
        cost="medium",
        time_to_effect="tens of minutes",
        feasibility="medium",
        expected_risk_reduction=0.5,
        applicable_event_types=["traffic", "water_level"],
        requires_human_approval=True,
    ),
]


def catalogue_by_id() -> dict[str, ActionCatalogueItem]:
    return {item.action_id: item for item in DEFAULT_ACTIONS}
