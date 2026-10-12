from fastapi import APIRouter, Depends

from urban_sentinel.api.deps import get_service
from urban_sentinel.domain.departments import DEPARTMENTS
from urban_sentinel.intelligence.department_delivery import configured_webhooks
from urban_sentinel.intelligence.service import IntelligenceService

router = APIRouter(prefix="/api/v1/departments", tags=["departments"])


@router.get("")
async def list_departments(service: IntelligenceService = Depends(get_service)) -> dict:
    try:
        configured = configured_webhooks(service)
    except ValueError:
        configured = {}
    return {
        "departments": [
            item.model_copy(update={"delivery_configured": item.department_id in configured}).model_dump(mode="json")
            for item in DEPARTMENTS
        ],
        "delivery_configured": bool(configured),
    }
