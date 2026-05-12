from fastapi import APIRouter
from fastapi.responses import JSONResponse

from app.services.health_service import get_liveness, get_system_health

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return get_liveness()


@router.get("/ready")
def ready() -> JSONResponse:
    result = get_system_health()
    status_code = 503 if result.get("status") == "degraded" else 200
    return JSONResponse(content=result, status_code=status_code)
