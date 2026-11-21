from datetime import UTC, datetime

from erw.auth import create_session_token
from erw.models import ChatMemory, Project, ProjectMember, User

NOW = datetime(2026, 11, 4, 1, 0, tzinfo=UTC)


def _world(session):
    pm = User(email="pm@example.com", name="PM", password_hash="x", is_admin=False, created_at=NOW)
    other = User(email="other@example.com", name="Other", password_hash="x", is_admin=False, created_at=NOW)
    session.add_all([pm, other])
    session.flush()
    session.add(Project(key="DEMO", name="Demo"))
    session.flush()
    session.add_all(
        [
            ProjectMember(project_key="DEMO", user_id=pm.id, role="pm"),
            ProjectMember(project_key="DEMO", user_id=other.id, role="pm"),
        ]
    )
    session.commit()
    return {"pm": pm, "other": other}


def login(client, user, settings):
    token = create_session_token(user.id, settings.session_secret)
    client.cookies.set(settings.session_cookie_name, token)


def test_memory_crud_scoped_to_user(client, settings, session):
    world = _world(session)
    login(client, world["pm"], settings)
    created = client.post(
        "/api/chat/memories",
        json={"project": "DEMO", "kind": "preference", "text": "Ưu tiên blocker trước"},
    )
    assert created.status_code == 200
    mid = created.json()["id"]
    listed = client.get("/api/chat/memories", params={"project": "DEMO"})
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    patched = client.patch(
        f"/api/chat/memories/{mid}",
        params={"project": "DEMO"},
        json={"text": "Ưu tiên blocker và due"},
    )
    assert patched.status_code == 200
    assert patched.json()["text"] == "Ưu tiên blocker và due"
    login(client, world["other"], settings)
    assert client.get("/api/chat/memories", params={"project": "DEMO"}).json() == []
    assert client.delete(f"/api/chat/memories/{mid}", params={"project": "DEMO"}).status_code == 404
    login(client, world["pm"], settings)
    assert client.delete(f"/api/chat/memories/{mid}", params={"project": "DEMO"}).status_code == 200
    assert client.get("/api/chat/memories", params={"project": "DEMO"}).json() == []


def test_episode_not_listed_or_editable_via_api(client, settings, session):
    world = _world(session)
    session.add(
        ChatMemory(
            user_id=world["pm"].id,
            project_key="DEMO",
            kind="episode",
            text="đã hỏi risky",
            metadata_json={},
            created_at=NOW,
            updated_at=NOW,
        )
    )
    session.commit()
    login(client, world["pm"], settings)
    assert client.get("/api/chat/memories", params={"project": "DEMO"}).json() == []


def test_load_user_project_memory_prefers_prefs_over_episode_flood(session):
    from erw.pipeline.chat_memory import load_user_project_memory

    world = _world(session)
    uid = world["pm"].id
    session.add(
        ChatMemory(
            user_id=uid,
            project_key="DEMO",
            kind="preference",
            text="Ưu tiên blocker",
            metadata_json={},
            created_at=NOW,
            updated_at=NOW,
        )
    )
    for i in range(12):
        session.add(
            ChatMemory(
                user_id=uid,
                project_key="DEMO",
                kind="episode",
                text=f"ep-{i}",
                metadata_json={},
                created_at=NOW,
                updated_at=NOW,
            )
        )
    session.commit()
    rows = load_user_project_memory(session, uid, "DEMO", limit=20)
    kinds = [row.kind for row in rows]
    assert kinds.count("preference") == 1
    assert kinds.count("episode") == 5
    assert kinds[0] == "preference"
