import logging
import re
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from erw import jobs
from erw.api import health, webhooks
from erw.db import init_db, make_engine
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
) -> FastAPI:
    settings = settings or get_settings()
    own_engine = engine is None
    engine = engine or make_engine(settings.db_url)
    init_db(engine)
    jobs.configure(settings, engine)
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
    app.include_router(health.router)
    app.include_router(webhooks.router)
    return app
