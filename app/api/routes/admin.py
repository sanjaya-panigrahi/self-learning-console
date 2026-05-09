from fastapi import APIRouter

from app.api.routes.admin_ingestion import router as ingestion_router
from app.api.routes.admin_observability import router as observability_router
from app.api.routes.admin_retrieval import router as retrieval_router
from app.api.routes.admin_wiki import router as wiki_router
from app.services.ingestion_service import get_ingestion_report as get_last_ingestion_report

router = APIRouter()
router.include_router(ingestion_router)
router.include_router(retrieval_router)
router.include_router(observability_router)
router.include_router(wiki_router)
