import hmac

from fastapi import APIRouter, HTTPException, Request

from erw import jobs

router = APIRouter()


@router.post("/webhooks/jira/{secret}")
async def jira_webhook(secret: str, request: Request) -> dict:
    expected = request.app.state.settings.jira_webhook_secret
    if not expected or not hmac.compare_digest(secret.encode(), expected.encode()):
        raise HTTPException(status_code=404)
    try:
        payload = await request.json()
    except ValueError:
        raise HTTPException(status_code=400, detail="invalid JSON") from None
    jobs.executor.submit(jobs.handle_webhook, payload)
    return {"accepted": True}
