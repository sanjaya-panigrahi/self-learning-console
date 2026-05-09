from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles

from app.api.routes import api_router
from app.core.config.settings import get_settings
from app.core.observability.langsmith import configure_langsmith

settings = get_settings()
configure_langsmith()

app = FastAPI(
    title=settings.app_name,
    version="0.1.0",
    description="V1 Training Agent API (Python/FastAPI)",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",
        "http://127.0.0.1:5173",
        "http://localhost:4173",
        "http://127.0.0.1:4173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router, prefix="/api")


@app.get("/dashboard/admin", include_in_schema=False)
def dashboard_admin_alias() -> RedirectResponse:
    return RedirectResponse(url="/dashboard/?mode=admin", status_code=307)


@app.get("/dashboard/user", include_in_schema=False)
def dashboard_user_alias() -> RedirectResponse:
    return RedirectResponse(url="/dashboard/?mode=user", status_code=307)

visual_preview_dir = Path(settings.local_index_path).parent.parent / "visual_previews"
visual_preview_dir.mkdir(parents=True, exist_ok=True)
app.mount("/visual-previews", StaticFiles(directory=visual_preview_dir), name="visual-previews")

dashboard_dist = Path(__file__).resolve().parents[1] / "ui" / "react-dashboard" / "dist"
if dashboard_dist.exists():
    app.mount("/dashboard/admin", StaticFiles(directory=dashboard_dist, html=True), name="dashboard-admin")
    app.mount("/dashboard/user", StaticFiles(directory=dashboard_dist, html=True), name="dashboard-user")
    app.mount("/dashboard", StaticFiles(directory=dashboard_dist, html=True), name="dashboard")
    dashboard_assets = dashboard_dist / "assets"
    if dashboard_assets.exists():
        app.mount("/assets", StaticFiles(directory=dashboard_assets), name="dashboard-assets")


@app.get("/")
def root() -> dict[str, str]:
    return {"message": f"{settings.app_name} is running"}


@app.get("/ready")
def root_ready() -> dict[str, object]:
    from app.services.health_service import get_system_health

    return get_system_health()
