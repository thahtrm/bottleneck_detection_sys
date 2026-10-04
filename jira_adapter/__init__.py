"""Adapter The Public Jira Dataset -> dòng sự kiện chuẩn cho TGN.

Package gồm:
- normalize.py : chuẩn hóa link type / issue type / priority (theo mapping của dataset)
- events.py    : issue document (Jira API v2) -> list Event
- eda.py       : chạy EDA per-instance, xuất báo cáo markdown + số liệu quyết định P1
"""
from .events import Event, extract_events
from .normalize import normalize_link_type, normalize_priority

__all__ = ["Event", "extract_events", "normalize_link_type", "normalize_priority"]
