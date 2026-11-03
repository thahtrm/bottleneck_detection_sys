from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import Engine

from erw import jobs
from erw.api import health, webhooks
from erw.db import init_db, make_engine
from erw.pipeline import alerts, evaluate
from erw.settings import Settings, get_settings


def create_app(
    settings: Settings | None = None, *, engine: Engine | None = None, catch_up_on_startup: bool = True
) -> FastAPI:
    settings = settings or get_settings()
    engine = engine or make_engine(settings.db_url)
    init_db(engine)
    jobs.configure(settings, engine)
    evaluate._dispatch = alerts.dispatch  # wired here to avoid an evaluate -> alerts import cycle

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        if catch_up_on_startup and settings.jira_base_url:
            jobs.executor.submit(jobs.run_catch_up)
        yield  # Task 12 starts the scheduler here

    app = FastAPI(title="Early Risk Web", lifespan=lifespan)
    app.state.settings = settings
    app.state.engine = engine
    app.include_router(health.router)
    app.include_router(webhooks.router)
    return app
