import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from erw.db import UTCDateTime

_AVATAR_PALETTE = (
    "#0052CC",
    "#00875A",
    "#6554C0",
    "#FF5630",
    "#FF991F",
    "#00B8D9",
    "#36B37E",
)


def default_avatar_color(seed: str | None) -> str:
    s = (seed or "").strip().lower()
    if not s:
        return _AVATAR_PALETTE[0]
    return _AVATAR_PALETTE[sum(ord(c) for c in s) % len(_AVATAR_PALETTE)]


def _gen_account_id() -> str:
    return f"acc-{uuid.uuid4().hex[:12]}"


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    password_hash: Mapped[str] = mapped_column(String)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    account_id: Mapped[str | None] = mapped_column(
        String, unique=True, index=True, nullable=True, default=_gen_account_id
    )
    avatar_url: Mapped[str | None] = mapped_column(String, nullable=True)
    avatar_color: Mapped[str | None] = mapped_column(String, nullable=True)
    job_title: Mapped[str | None] = mapped_column(String, nullable=True)
    department: Mapped[str | None] = mapped_column(String, nullable=True)
    timezone: Mapped[str] = mapped_column(String, default="Asia/Ho_Chi_Minh")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("is_admin", False)
        kwargs.setdefault("is_active", True)
        kwargs.setdefault("timezone", "Asia/Ho_Chi_Minh")
        if not kwargs.get("avatar_color"):
            kwargs["avatar_color"] = default_avatar_color(kwargs.get("name") or kwargs.get("email") or "")
        if not kwargs.get("account_id"):
            kwargs["account_id"] = _gen_account_id()
        super().__init__(**kwargs)


class Project(Base):
    __tablename__ = "projects"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    tracked: Mapped[bool] = mapped_column(Boolean, default=True)
    status_map: Mapped[Any] = mapped_column(JSON, default=dict)
    thresholds: Mapped[Any] = mapped_column(JSON, default=dict)
    description: Mapped[str] = mapped_column(Text, default="")
    lead_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    issue_seq: Mapped[int] = mapped_column(Integer, default=0)
    workflow: Mapped[Any] = mapped_column(JSON, default=dict)


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_key: Mapped[str] = mapped_column(ForeignKey("projects.key"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String)  # "pm" | "developer" | "viewer"


class Issue(Base):
    __tablename__ = "issues"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    project_key: Mapped[str] = mapped_column(String, index=True)
    parent_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    description: Mapped[str] = mapped_column(Text, default="")
    environment: Mapped[str] = mapped_column(Text, default="")
    issuetype: Mapped[str | None] = mapped_column(String)
    priority: Mapped[str | None] = mapped_column(String)
    priority_norm: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str | None] = mapped_column(String)
    status_category: Mapped[str] = mapped_column(String, default="new")  # new|indeterminate|done
    resolution: Mapped[str | None] = mapped_column(String, nullable=True)
    assignee_id: Mapped[str | None] = mapped_column(String)
    assignee_name: Mapped[str | None] = mapped_column(String)
    reporter_id: Mapped[str | None] = mapped_column(String, nullable=True)
    reporter_name: Mapped[str | None] = mapped_column(String, nullable=True)
    creator_id: Mapped[str | None] = mapped_column(String, nullable=True)
    creator_name: Mapped[str | None] = mapped_column(String, nullable=True)
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    duedate: Mapped[date | None] = mapped_column(Date)
    story_points: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[float] = mapped_column(Float, default=0.0, index=True)
    original_estimate_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    remaining_estimate_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    time_spent_seconds: Mapped[int] = mapped_column(Integer, default=0)
    labels: Mapped[Any] = mapped_column(JSON, default=list)
    version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    raw: Mapped[Any] = mapped_column(JSON, default=dict)

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("summary", "")
        kwargs.setdefault("description", "")
        kwargs.setdefault("environment", "")
        kwargs.setdefault("priority_norm", 0.0)
        kwargs.setdefault("status_category", "new")
        kwargs.setdefault("rank", 0.0)
        kwargs.setdefault("time_spent_seconds", 0)
        kwargs.setdefault("version", 1)
        if kwargs.get("labels") is None:
            kwargs["labels"] = []
        if kwargs.get("raw") is None:
            kwargs["raw"] = {}
        super().__init__(**kwargs)


class Change(Base):
    __tablename__ = "changes"
    __table_args__ = (UniqueConstraint("issue_key", "change_id", "idx"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_key: Mapped[str] = mapped_column(ForeignKey("issues.key"), index=True)
    change_id: Mapped[str] = mapped_column(String)
    idx: Mapped[int] = mapped_column(Integer, default=0)
    at: Mapped[datetime] = mapped_column(UTCDateTime)
    author_id: Mapped[str | None] = mapped_column(String, nullable=True)
    author_name: Mapped[str | None] = mapped_column(String, nullable=True)
    field: Mapped[str] = mapped_column(String)  # Jira changelog items[].field, lower-cased
    from_val: Mapped[str | None] = mapped_column(Text)
    to_val: Mapped[str | None] = mapped_column(Text)
    from_str: Mapped[str | None] = mapped_column(Text)
    to_str: Mapped[str | None] = mapped_column(Text)


class Link(Base):
    __tablename__ = "links"

    source_key: Mapped[str] = mapped_column(String, primary_key=True)
    target_key: Mapped[str] = mapped_column(String, primary_key=True)
    type_std: Mapped[str] = mapped_column(String, primary_key=True)
    direction: Mapped[str | None] = mapped_column(String)


class Sprint(Base):
    __tablename__ = "sprints"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_key: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    board_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String)
    goal: Mapped[str] = mapped_column(Text, default="")
    state: Mapped[str | None] = mapped_column(String)
    start_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    end_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    complete_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class IssueSprint(Base):
    __tablename__ = "issue_sprints"

    issue_key: Mapped[str] = mapped_column(ForeignKey("issues.key"), primary_key=True)
    sprint_id: Mapped[int] = mapped_column(ForeignKey("sprints.id"), primary_key=True)


class Version(Base):
    __tablename__ = "versions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_key: Mapped[str | None] = mapped_column(String, index=True)
    name: Mapped[str | None] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    start_date: Mapped[date | None] = mapped_column(Date, nullable=True)
    release_date: Mapped[date | None] = mapped_column(Date)
    released: Mapped[bool] = mapped_column(Boolean, default=False)


class IssueVersion(Base):
    __tablename__ = "issue_versions"

    issue_key: Mapped[str] = mapped_column(ForeignKey("issues.key"), primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("versions.id"), primary_key=True)
    relation_type: Mapped[str] = mapped_column(String, primary_key=True, default="fix")

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("relation_type", "fix")
        super().__init__(**kwargs)


class Comment(Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_key: Mapped[str] = mapped_column(ForeignKey("issues.key"), index=True)
    author_id: Mapped[str | None] = mapped_column(String, nullable=True)
    author_name: Mapped[str | None] = mapped_column(String, nullable=True)
    body: Mapped[str] = mapped_column(Text, default="")
    mentions: Mapped[Any] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    edited: Mapped[bool] = mapped_column(Boolean, default=False)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Attachment(Base):
    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_key: Mapped[str] = mapped_column(ForeignKey("issues.key"), index=True)
    author_id: Mapped[str | None] = mapped_column(String, nullable=True)
    author_name: Mapped[str | None] = mapped_column(String, nullable=True)
    filename: Mapped[str] = mapped_column(String)
    mime_type: Mapped[str] = mapped_column(String, default="application/octet-stream")
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    storage_path: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Worklog(Base):
    __tablename__ = "worklogs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_key: Mapped[str] = mapped_column(ForeignKey("issues.key"), index=True)
    author_id: Mapped[str | None] = mapped_column(String, nullable=True)
    author_name: Mapped[str | None] = mapped_column(String, nullable=True)
    time_spent_seconds: Mapped[int] = mapped_column(Integer)
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    comment: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class IssueWatcher(Base):
    __tablename__ = "watchers"

    issue_key: Mapped[str] = mapped_column(ForeignKey("issues.key"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class IssueVote(Base):
    __tablename__ = "votes"

    issue_key: Mapped[str] = mapped_column(ForeignKey("issues.key"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class Component(Base):
    __tablename__ = "components"
    __table_args__ = (UniqueConstraint("project_key", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_key: Mapped[str] = mapped_column(ForeignKey("projects.key"), index=True)
    name: Mapped[str] = mapped_column(String)
    description: Mapped[str] = mapped_column(Text, default="")
    lead_user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class IssueComponent(Base):
    __tablename__ = "issue_components"

    issue_key: Mapped[str] = mapped_column(ForeignKey("issues.key"), primary_key=True)
    component_id: Mapped[int] = mapped_column(ForeignKey("components.id"), primary_key=True)


class Score(Base):
    __tablename__ = "scores"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_key: Mapped[str] = mapped_column(String, index=True)
    scorer: Mapped[str] = mapped_column(String)
    as_of: Mapped[datetime] = mapped_column(UTCDateTime)
    value: Mapped[float | None] = mapped_column(Float)
    level: Mapped[str | None] = mapped_column(String)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    extra: Mapped[Any] = mapped_column(JSON, default=dict)
    deadline_type: Mapped[str | None] = mapped_column(String)
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    factors: Mapped[Any] = mapped_column(JSON, default=list)


class RiskState(Base):
    __tablename__ = "risk_state"

    issue_key: Mapped[str] = mapped_column(String, primary_key=True)
    level: Mapped[str | None] = mapped_column(String)
    prev_level: Mapped[str | None] = mapped_column(String)
    level_raised_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    delay_value: Mapped[float | None] = mapped_column(Float)
    crit_score: Mapped[float | None] = mapped_column(Float)
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)
    blocked: Mapped[bool] = mapped_column(Boolean, default=False)
    deadline_type: Mapped[str | None] = mapped_column(String)
    deadline_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    deadline_label: Mapped[str | None] = mapped_column(String)
    factors: Mapped[Any] = mapped_column(JSON, default=list)
    last_alerted_level: Mapped[str | None] = mapped_column(String)
    dismissed_at_level: Mapped[str | None] = mapped_column(String, nullable=True)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)


class Notification(Base):
    __tablename__ = "notifications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    kind: Mapped[str] = mapped_column(String)
    issue_key: Mapped[str | None] = mapped_column(String)
    project_key: Mapped[str | None] = mapped_column(String)
    dedup_key: Mapped[str] = mapped_column(String, unique=True)
    text: Mapped[str] = mapped_column(Text)
    sent_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String, default="pending")


class Suggestion(Base):
    __tablename__ = "suggestions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_key: Mapped[str] = mapped_column(String, index=True)
    issue_updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    model: Mapped[str] = mapped_column(String)
    output: Mapped[Any] = mapped_column(JSON, default=dict)
    valid: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Action(Base):
    __tablename__ = "actions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_key: Mapped[str] = mapped_column(String, index=True)
    suggestion_id: Mapped[int | None] = mapped_column(ForeignKey("suggestions.id"), nullable=True)
    items: Mapped[Any] = mapped_column(JSON, default=list)
    status: Mapped[str] = mapped_column(String, default="pending")  # "pending" | "applied" | "conflict" | "failed"
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    result: Mapped[Any] = mapped_column(JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class KV(Base):
    __tablename__ = "kv"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        Index("ix_chat_messages_user_project_created", "user_id", "project_key", "created_at"),
        UniqueConstraint("dedup_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_key: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # user | assistant | report | urgent
    body: Mapped[str] = mapped_column(Text)
    recommendation_status: Mapped[str] = mapped_column(String)  # pending | ready | failed | skipped
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    dedup_key: Mapped[str | None] = mapped_column(String, nullable=True)


class ReportSlot(Base):
    __tablename__ = "report_slots"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    time_hhmm: Mapped[str] = mapped_column(String, primary_key=True)


class ReportFile(Base):
    """On-disk daily report artifact linked to a timeline ChatMessage(kind=report)."""

    __tablename__ = "report_files"
    __table_args__ = (
        Index("ix_report_files_user_project_created", "user_id", "project_key", "created_at"),
        UniqueConstraint("message_id"),
        UniqueConstraint("user_id", "project_key", "rel_path"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_key: Mapped[str] = mapped_column(String)
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id"), index=True)
    slot_hhmm: Mapped[str] = mapped_column(String)
    report_date: Mapped[str] = mapped_column(String)  # YYYY-MM-DD local
    rel_path: Mapped[str] = mapped_column(String)  # relative to reports_dir
    preview: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    hidden_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class ChatMemory(Base):
    __tablename__ = "chat_memories"
    __table_args__ = (Index("ix_chat_memories_user_project_kind", "user_id", "project_key", "kind", "updated_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    project_key: Mapped[str] = mapped_column(String)
    kind: Mapped[str] = mapped_column(String)  # preference | note | episode
    text: Mapped[str] = mapped_column(Text)
    metadata_json: Mapped[Any] = mapped_column("metadata", JSON, default=dict)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ChatRagChunk(Base):
    __tablename__ = "chat_rag_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    corpus: Mapped[str] = mapped_column(String, default="seed_help")
    project_key: Mapped[str | None] = mapped_column(String, nullable=True)
    source_uri: Mapped[str] = mapped_column(String)
    text: Mapped[str] = mapped_column(Text)
    embedding_model: Mapped[str] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class ChatAgentRun(Base):
    __tablename__ = "chat_agent_runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    message_id: Mapped[int] = mapped_column(ForeignKey("chat_messages.id"), index=True)
    status: Mapped[str] = mapped_column(String)  # running | ready | failed | skipped
    steps_json: Mapped[Any] = mapped_column(JSON, default=list)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
