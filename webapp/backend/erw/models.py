from datetime import date, datetime
from typing import Any

from sqlalchemy import JSON, Boolean, Date, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from erw.db import UTCDateTime


class Base(DeclarativeBase):
    pass


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


class KV(Base):
    __tablename__ = "kv"

    key: Mapped[str] = mapped_column(String, primary_key=True)
    value: Mapped[str | None] = mapped_column(Text)
