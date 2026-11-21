from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from erw.db import UTCDateTime


class Base(DeclarativeBase):
    pass


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    email: Mapped[str] = mapped_column(String, unique=True, index=True)
    name: Mapped[str] = mapped_column(String)
    password_hash: Mapped[str] = mapped_column(String)
    is_admin: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)


class Project(Base):
    __tablename__ = "projects"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    name: Mapped[str] = mapped_column(String, default="")
    tracked: Mapped[bool] = mapped_column(Boolean, default=True)
    status_map: Mapped[Any] = mapped_column(JSON, default=dict)
    thresholds: Mapped[Any] = mapped_column(JSON, default=dict)


class ProjectMember(Base):
    __tablename__ = "project_members"

    project_key: Mapped[str] = mapped_column(ForeignKey("projects.key"), primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), primary_key=True)
    role: Mapped[str] = mapped_column(String)  # "pm" | "viewer"


class Issue(Base):
    __tablename__ = "issues"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    project_key: Mapped[str] = mapped_column(String, index=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    issuetype: Mapped[str | None] = mapped_column(String)
    priority: Mapped[str | None] = mapped_column(String)
    priority_norm: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str | None] = mapped_column(String)
    status_category: Mapped[str] = mapped_column(String, default="new")  # new|indeterminate|done
    assignee_id: Mapped[str | None] = mapped_column(String)
    assignee_name: Mapped[str | None] = mapped_column(String)
    duedate: Mapped[date | None] = mapped_column(Date)
    story_points: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    updated_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    resolved_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    deleted_at: Mapped[datetime | None] = mapped_column(UTCDateTime)
    raw: Mapped[Any] = mapped_column(JSON, default=dict)


class Change(Base):
    __tablename__ = "changes"
    __table_args__ = (UniqueConstraint("issue_key", "change_id", "idx"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    issue_key: Mapped[str] = mapped_column(ForeignKey("issues.key"), index=True)
    change_id: Mapped[str] = mapped_column(String)
    idx: Mapped[int] = mapped_column(Integer, default=0)
    at: Mapped[datetime] = mapped_column(UTCDateTime)
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    board_id: Mapped[int | None] = mapped_column(Integer)
    name: Mapped[str | None] = mapped_column(String)
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

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    project_key: Mapped[str | None] = mapped_column(String)
    name: Mapped[str | None] = mapped_column(String)
    release_date: Mapped[date | None] = mapped_column(Date)
    released: Mapped[bool] = mapped_column(Boolean, default=False)


class IssueVersion(Base):
    __tablename__ = "issue_versions"

    issue_key: Mapped[str] = mapped_column(ForeignKey("issues.key"), primary_key=True)
    version_id: Mapped[int] = mapped_column(ForeignKey("versions.id"), primary_key=True)


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
