import logging
import re
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Engine

from erw import jobs
from erw.api import actions, admin, auth, dashboard, health, issues, projects, webhooks
from erw.db import init_db, make_engine
from erw.integrations import llm
from erw.pipeline import alerts, evaluate
from erw.settings import Settings, get_settings


def mask_webhook_secret(text: str) -> str:
    """Mask Jira webhook secret in URLs (e.g. /webhooks/jira/<secret> -> /webhooks/jira/***)."""
    return re.sub(r"/webhooks/jira/[^/\s?]+", "/webhooks/jira/***", text)


class WebhookSecretFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = mask_webhook_secret(record.msg)
        if record.args:
            if isinstance(record.args, tuple):
                record.args = tuple(mask_webhook_secret(a) if isinstance(a, str) else a for a in record.args)
            elif isinstance(record.args, dict):
                record.args = {k: (mask_webhook_secret(v) if isinstance(v, str) else v) for k, v in record.args.items()}
        return True


def create_app(
    settings: Settings | None = None, *, engine: Engine | None = None, catch_up_on_startup: bool = True,
    start_scheduler_on_startup: bool = True,
    frontend_dist: Path | str | None = None,
) -> FastAPI:
    settings = settings or get_settings()
    own_engine = engine is None
    engine = engine or make_engine(settings.db_url)
    init_db(engine)
    jobs.configure(settings, engine)
    llm.set_engine(engine)
    evaluate._dispatch = alerts.dispatch  # wired here to avoid an evaluate -> alerts import cycle

    access_logger = logging.getLogger("uvicorn.access")
    if not any(isinstance(f, WebhookSecretFilter) for f in access_logger.filters):
        access_logger.addFilter(WebhookSecretFilter())

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if catch_up_on_startup and settings.jira_base_url:
            jobs.executor.submit(jobs.run_catch_up)
        app.state.scheduler = jobs.start_scheduler(settings) if start_scheduler_on_startup else None
        try:
            yield
        finally:
            if app.state.scheduler is not None:
                app.state.scheduler.shutdown(wait=False)
            if own_engine:
                engine.dispose()

    app = FastAPI(title="Early Risk Web", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.dependency_overrides[get_settings] = lambda: settings
    app.include_router(health.router)
    app.include_router(webhooks.router)
    app.include_router(auth.router)
    app.include_router(projects.projects_router)
    app.include_router(issues.issues_router)
    app.include_router(actions.actions_router)
    app.include_router(dashboard.dashboard_router)
    app.include_router(admin.admin_router)

    if frontend_dist is None:
        frontend_dist = Path(__file__).resolve().parent.parent.parent / "frontend" / "dist"
    else:
        frontend_dist = Path(frontend_dist)

    if frontend_dist.is_dir():
        assets_dir = frontend_dist / "assets"
        if assets_dir.is_dir():
            app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

        index_html = frontend_dist / "index.html"
        if index_html.is_file():

            @app.middleware("http")
            async def spa_fallback_middleware(request: Request, call_next):
                response = await call_next(request)
                if (
                    response.status_code == 404
                    and request.method == "GET"
                    and not request.url.path.startswith(("/api", "/webhooks", "/healthz"))
                ):
                    clean_path = request.url.path.lstrip("/")
                    target_file = frontend_dist / clean_path
                    if clean_path and target_file.is_file():
                        return FileResponse(target_file)
                    return FileResponse(index_html)
                return response

    return app


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("erw.main:create_app", factory=True, host="0.0.0.0", port=8000)

