from fastapi import APIRouter

from urban_sentinel.domain.departments import DEPARTMENTS

router = APIRouter(prefix="/api/v1/departments", tags=["departments"])


@router.get("")
async def list_departments() -> dict:
    return {
        "departments": [item.model_dump(mode="json") for item in DEPARTMENTS],
        "delivery_configured": False,
    }
