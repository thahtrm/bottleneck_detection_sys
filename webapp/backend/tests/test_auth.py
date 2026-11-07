from __future__ import annotations

import time
from datetime import UTC, datetime

import pytest
from fastapi import Depends, HTTPException
from sqlalchemy import select

from erw import cli
from erw.auth import (
    create_session_token,
    hash_password,
    require_admin,
    require_authenticated_user,
    verify_password,
    verify_session_token,
)
from erw.models import User
from erw.settings import Settings

# ---------------------------------------------------------------------------
# 1. Password Hashing & Verification
# ---------------------------------------------------------------------------


def test_hash_and_verify_password():
    password = "correct_horse_battery_staple"
    hashed = hash_password(password)

    assert hashed.startswith("pbkdf2:sha256:100000$")
    parts = hashed.split("$")
    assert len(parts) == 3
    assert len(parts[1]) == 32  # 16 bytes hex = 32 chars
    assert len(parts[2]) == 64  # sha256 hex = 64 chars

    assert verify_password(password, hashed) is True
    assert verify_password("wrong_password", hashed) is False
    assert verify_password("", hashed) is False


def test_hash_password_salt_randomness():
    p = "same_password"
    h1 = hash_password(p)
    h2 = hash_password(p)
    assert h1 != h2
    assert verify_password(p, h1) is True
    assert verify_password(p, h2) is True


def test_verify_password_malformed_hashes():
    assert verify_password("pass", "") is False
    assert verify_password("pass", "invalid_format") is False
    assert verify_password("pass", "pbkdf2:md5:1000$salt$hash") is False
    assert verify_password("pass", "pbkdf2:sha256:invalid$salt$hash") is False
    assert verify_password("pass", "pbkdf2:sha256:1000$nothex$nothex") is False
    assert verify_password("pass", None) is False  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Session Token Creation & Verification
# ---------------------------------------------------------------------------


def test_session_token_valid():
    secret = "test-secret-key"
    token = create_session_token(42, secret)
    user_id = verify_session_token(token, secret, max_age=3600)
    assert user_id == 42


def test_session_token_tampering():
    secret = "test-secret-key"
    token = create_session_token(42, secret)
    parts = token.split(".")

    # Tamper user id
    tampered_user = f"99.{parts[1]}.{parts[2]}"
    assert verify_session_token(tampered_user, secret, max_age=3600) is None

    # Tamper timestamp
    tampered_ts = f"{parts[0]}.{int(parts[1]) - 100}.{parts[2]}"
    assert verify_session_token(tampered_ts, secret, max_age=3600) is None

    # Tamper signature
    tampered_sig = f"{parts[0]}.{parts[1]}.{'0' * 64}"
    assert verify_session_token(tampered_sig, secret, max_age=3600) is None

    # Wrong secret
    assert verify_session_token(token, "wrong-secret", max_age=3600) is None


def test_session_token_expiration():
    secret = "test-secret-key"
    now = int(time.time())
    old_ts = now - 7200  # 2 hours ago
    token = create_session_token(42, secret, timestamp=old_ts)

    # Expired when max_age is 3600 (1 hour)
    assert verify_session_token(token, secret, max_age=3600, current_time=now) is None
    # Still valid when max_age is 10000
    assert verify_session_token(token, secret, max_age=10000, current_time=now) == 42


def test_session_token_future_clock_skew():
    secret = "test-secret-key"
    now = int(time.time())
    future_token = create_session_token(42, secret, timestamp=now + 120)  # 2 minutes into future
    assert verify_session_token(future_token, secret, max_age=3600, current_time=now) is None


def test_session_token_malformed():
    secret = "test-secret-key"
    assert verify_session_token("", secret, 3600) is None
    assert verify_session_token("invalid", secret, 3600) is None
    assert verify_session_token("1.2", secret, 3600) is None
    assert verify_session_token("1.2.3.4", secret, 3600) is None
    assert verify_session_token("abc.def.ghi", secret, 3600) is None
    assert verify_session_token(None, secret, 3600) is None  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 3. RBAC Dependencies
# ---------------------------------------------------------------------------


def test_rbac_dependencies_unit():
    admin = User(id=1, email="admin@example.com", name="Admin", password_hash="h", is_admin=True, created_at=datetime.now(UTC))
    regular = User(id=2, email="user@example.com", name="User", password_hash="h", is_admin=False, created_at=datetime.now(UTC))

    assert require_authenticated_user(admin) is admin
    assert require_authenticated_user(regular) is regular

    with pytest.raises(HTTPException) as exc_info:
        require_authenticated_user(None)
    assert exc_info.value.status_code == 401
    assert exc_info.value.detail == "Not authenticated"

    assert require_admin(admin) is admin

    with pytest.raises(HTTPException) as exc_info:
        require_admin(regular)
    assert exc_info.value.status_code == 403
    assert exc_info.value.detail == "Admin privileges required"


# ---------------------------------------------------------------------------
# 4. API Endpoints: Login, Me, Logout, and RBAC
# ---------------------------------------------------------------------------


@pytest.fixture
def test_users(session):
    u_admin = User(
        email="admin@example.com",
        name="Admin User",
        password_hash=hash_password("admin_pass"),
        is_admin=True,
        created_at=datetime.now(UTC),
    )
    u_regular = User(
        email="member@example.com",
        name="Regular Member",
        password_hash=hash_password("member_pass"),
        is_admin=False,
        created_at=datetime.now(UTC),
    )
    session.add_all([u_admin, u_regular])
    session.commit()
    session.refresh(u_admin)
    session.refresh(u_regular)
    return {"admin": u_admin, "member": u_regular}


def test_api_login_success_and_me(client, test_users, settings):
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "admin_pass"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["id"] == test_users["admin"].id
    assert data["email"] == "admin@example.com"
    assert data["name"] == "Admin User"
    assert data["is_admin"] is True
    assert data["jira_base_url"] == settings.jira_base_url.rstrip("/")

    # Cookie is set
    assert "erw_session" in client.cookies

    # GET /api/auth/me returns logged in user
    me_resp = client.get("/api/auth/me")
    assert me_resp.status_code == 200
    assert me_resp.json() == data


def test_api_login_case_insensitive_email(client, test_users):
    resp = client.post(
        "/api/auth/login",
        json={"email": "  ADMIN@Example.COM  ", "password": "admin_pass"},
    )
    assert resp.status_code == 200
    assert resp.json()["email"] == "admin@example.com"


def test_api_login_invalid_credentials(client, test_users):
    # Wrong password
    resp = client.post(
        "/api/auth/login",
        json={"email": "admin@example.com", "password": "wrong_password"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"
    assert "erw_session" not in client.cookies

    # Unknown user
    resp = client.post(
        "/api/auth/login",
        json={"email": "nobody@example.com", "password": "pass"},
    )
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Invalid email or password"


def test_api_me_unauthenticated(client):
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


def test_api_me_invalid_cookie(client):
    client.cookies.set("erw_session", "invalid.token.payload")
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401
    assert resp.json()["detail"] == "Not authenticated"


def test_api_logout(client, test_users):
    login_resp = client.post(
        "/api/auth/login",
        json={"email": "member@example.com", "password": "member_pass"},
    )
    assert login_resp.status_code == 200
    assert client.get("/api/auth/me").status_code == 200

    logout_resp = client.post("/api/auth/logout")
    assert logout_resp.status_code == 200
    assert logout_resp.json() == {"status": "logged_out"}

    # Cookie deleted / cleared; subsequent /me fails
    assert client.get("/api/auth/me").status_code == 401


def test_require_admin_protects_route(client, test_users):
    # Register an admin-protected endpoint to verify RBAC integration
    app = client.app

    @app.get("/api/test-admin-route")
    def test_admin_route(user: User = Depends(require_admin)):
        return {"admin": user.email}

    # 1. Unauthenticated -> 401
    assert client.get("/api/test-admin-route").status_code == 401

    # 2. Member logged in -> 403 Forbidden
    client.post("/api/auth/login", json={"email": "member@example.com", "password": "member_pass"})
    resp = client.get("/api/test-admin-route")
    assert resp.status_code == 403
    assert resp.json()["detail"] == "Admin privileges required"

    # 3. Admin logged in -> 200 OK
    client.post("/api/auth/login", json={"email": "admin@example.com", "password": "admin_pass"})
    admin_resp = client.get("/api/test-admin-route")
    assert admin_resp.status_code == 200
    assert admin_resp.json() == {"admin": "admin@example.com"}


# ---------------------------------------------------------------------------
# 5. CLI create-admin
# ---------------------------------------------------------------------------


def test_cli_create_admin(tmp_path, monkeypatch):
    db_file = tmp_path / "test_cli.db"
    cli_settings = Settings(
        _env_file=None,
        db_url=f"sqlite:///{db_file}",
    )
    monkeypatch.setattr(cli, "get_settings", lambda: cli_settings)

    # 1. First run: create admin
    ret = cli.main([
        "create-admin",
        "--email", "admin@domain.test",
        "--name", "Lead Admin",
        "--password", "TopSecret123",
    ])
    assert ret == 0

    from erw.db import SessionLocal, make_engine
    eng = make_engine(cli_settings.db_url)
    with SessionLocal(bind=eng) as s:
        user = s.execute(select(User).where(User.email == "admin@domain.test")).scalar_one_or_none()
        assert user is not None
        assert user.name == "Lead Admin"
        assert user.is_admin is True
        assert verify_password("TopSecret123", user.password_hash) is True

    # 2. Duplicate email should fail with 1
    ret_duplicate = cli.main([
        "create-admin",
        "--email", "ADMIN@domain.test",
        "--name", "Another Admin",
        "--password", "other_password",
    ])
    assert ret_duplicate == 1
