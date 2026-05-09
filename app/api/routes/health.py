from fastapi import APIRouter

from app.services.health_service import get_liveness, get_system_health

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return get_liveness()


@router.get("/ready")
def ready() -> dict[str, object]:
    return get_system_health()
