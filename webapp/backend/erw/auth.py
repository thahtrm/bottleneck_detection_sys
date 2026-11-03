from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from erw.db import get_session
from erw.models import User
from erw.settings import Settings, get_settings


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    derived = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, 100_000)
    return f"pbkdf2:sha256:100000${salt.hex()}${derived.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    try:
        parts = stored_hash.split("$")
        if len(parts) != 3:
            return False
        header, salt_hex, hash_hex = parts
        algo, hash_name, iterations_str = header.split(":")
        if algo != "pbkdf2":
            return False
        iterations = int(iterations_str)
        salt = bytes.fromhex(salt_hex)
        derived = hashlib.pbkdf2_hmac(hash_name, password.encode("utf-8"), salt, iterations)
        return hmac.compare_digest(derived.hex(), hash_hex)
    except Exception:
        return False


def create_session_token(user_id: int, secret: str, *, timestamp: int | None = None) -> str:
    ts = int(time.time()) if timestamp is None else int(timestamp)
    payload = f"{user_id}.{ts}"
    sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return f"{payload}.{sig}"


def verify_session_token(token: str, secret: str, max_age: int, *, current_time: int | None = None) -> int | None:
    if not token or not isinstance(token, str):
        return None
    parts = token.split(".")
    if len(parts) != 3:
        return None
    user_id_str, ts_str, sig = parts
    try:
        user_id = int(user_id_str)
        timestamp = int(ts_str)
    except (ValueError, TypeError):
        return None

    payload = f"{user_id}.{timestamp}"
    expected_sig = hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return None

    now = int(time.time()) if current_time is None else int(current_time)
    if timestamp > now + 60:
        return None
    if (now - timestamp) > max_age:
        return None

    return user_id


def get_current_user(
    request: Request,
    session: Session = Depends(get_session),
    settings: Settings = Depends(get_settings),
) -> User | None:
    app_settings = getattr(request.app.state, "settings", None) or settings
    token = request.cookies.get(app_settings.session_cookie_name)
    if not token:
        return None
    user_id = verify_session_token(
        token=token,
        secret=app_settings.session_secret,
        max_age=app_settings.session_max_age_seconds,
    )
    if user_id is None:
        return None
    return session.get(User, user_id)


def require_authenticated_user(user: User | None = Depends(get_current_user)) -> User:
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    return user


def require_admin(user: User = Depends(require_authenticated_user)) -> User:
    if not user.is_admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin privileges required",
        )
    return user
