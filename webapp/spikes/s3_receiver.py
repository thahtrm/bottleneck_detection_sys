"""Spike S3: receive Jira Cloud webhooks and dump each payload to var/s3/.

Run:  S3_SECRET=... .venv/bin/uvicorn webapp.spikes.s3_receiver:app --port 8000
Expose the port with an ngrok static domain, then register the webhook with s3_register.py.
"""
from __future__ import annotations

import hmac
import json
import os
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request

OUT = Path(os.environ.get("S3_OUT", "var/s3"))
SECRET = os.environ["S3_SECRET"]

app = FastAPI()


@app.post("/webhooks/jira/{secret}")
async def receive(secret: str, request: Request) -> dict:
    if not hmac.compare_digest(secret, SECRET):
        raise HTTPException(status_code=404)
    received = time.time()
    payload = await request.json()
    event = str(payload.get("webhookEvent", "unknown")).replace(":", "_")
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{received:.3f}-{event}.json"
    path.write_text(json.dumps({"received_at": received, "payload": payload}, ensure_ascii=False, indent=2))
    issue = (payload.get("issue") or {}).get("key")
    print(f"[s3] {event} issue={issue} jira_ts={payload.get('timestamp')} lag_s="
          f"{received - payload['timestamp'] / 1000 if payload.get('timestamp') else 'n/a'} -> {path.name}")
    return {"accepted": True}
