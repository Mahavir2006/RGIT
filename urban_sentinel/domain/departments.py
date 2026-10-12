from __future__ import annotations

from pydantic import BaseModel


class Department(BaseModel):
    department_id: str
    name: str
    description: str
    delivery_configured: bool = False


DEPARTMENTS: tuple[Department, ...] = (
    Department(
        department_id="drainage",
        name="Drainage and Stormwater",
        description="Drain, culvert, and stormwater infrastructure reports.",
    ),
    Department(
        department_id="water_resources",
        name="Water Resources",
        description="Water levels, reservoirs, and water supply reports.",
    ),
    Department(
        department_id="roads_traffic",
        name="Roads and Traffic",
        description="Road blockage, traffic disruption, and access reports.",
    ),
    Department(
        department_id="environment",
        name="Environment and Air Quality",
        description="Air quality and environmental condition reports.",
    ),
    Department(
        department_id="emergency_management",
        name="Emergency Management",
        description="Cross-department incidents needing coordination.",
    ),
)


def departments_by_id() -> dict[str, Department]:
    return {item.department_id: item for item in DEPARTMENTS}
