from fastapi import FastAPI

from erw.api import health
from erw.db import init_db, make_engine
from erw.settings import Settings, get_settings


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    app = FastAPI(title="Early Risk Web")
    engine = make_engine(settings.db_url)
    init_db(engine)
    app.state.settings = settings
    app.state.engine = engine
    app.include_router(health.router)
    return app
