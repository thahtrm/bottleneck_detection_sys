from fastapi import APIRouter, Request
from sqlalchemy.orm import Session

from erw.models import KV

router = APIRouter()


@router.get("/healthz")
def healthz(request: Request) -> dict:
    with Session(request.app.state.engine) as s:
        row = s.get(KV, "last_webhook_at")
        return {"status": "ok", "last_webhook_at": row.value if row else None}
