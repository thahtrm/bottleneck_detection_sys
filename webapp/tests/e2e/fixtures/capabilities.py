from __future__ import annotations

import importlib.util
from typing import Any, get_args

import pytest


def has_setting(field_name: str) -> bool:
    from erw.settings import Settings

    return field_name in Settings.model_fields


def has_column(model_cls: type[Any], column_name: str) -> bool:
    table = getattr(model_cls, "__table__", None)
    if table is not None and column_name in table.columns:
        return True
    return hasattr(model_cls, column_name)


def has_table(table_name: str) -> bool:
    from erw.models import Base

    return table_name in Base.metadata.tables


def has_local_jira_client() -> bool:
    return importlib.util.find_spec("erw.integrations.local_jira") is not None


def get_local_jira_client_cls() -> type[Any] | None:
    if not has_local_jira_client():
        return None
    from erw.integrations.local_jira import LocalJiraClient

    return LocalJiraClient


def supported_member_roles() -> tuple[str, ...]:
    try:
        from erw.api import projects as projects_api

        member_role = getattr(projects_api, "MemberRole", None)
        args = get_args(member_role) if member_role is not None else ()
        if args:
            return tuple(str(a) for a in args)
    except Exception:
        pass
    return ("pm", "viewer")


def supports_member_role(role: str) -> bool:
    return role in supported_member_roles()


def _normalize_route_path(path: str) -> str:
    stripped = path.rstrip("/")
    return stripped or "/"


def _iter_routes(routes: Any):
    for route in routes or ():
        if hasattr(route, "original_router"):
            yield from _iter_routes(getattr(route.original_router, "routes", ()))
        elif hasattr(route, "routes"):
            yield from _iter_routes(getattr(route, "routes", ()))
        else:
            yield route


def has_route(app: Any, method: str, path: str) -> bool:
    method_u = method.upper()
    method_l = method.lower()
    target = _normalize_route_path(path)

    for route in _iter_routes(getattr(app, "routes", ())):
        route_path = getattr(route, "path", None)
        methods = getattr(route, "methods", None) or set()
        if isinstance(route_path, str) and _normalize_route_path(route_path) == target and method_u in methods:
            return True

    openapi_fn = getattr(app, "openapi", None)
    if callable(openapi_fn):
        try:
            paths = openapi_fn().get("paths", {})
            for p, ops in paths.items():
                if _normalize_route_path(p) == target and isinstance(ops, dict) and method_l in ops:
                    return True
        except Exception:
            pass
    return False


def require_capability(condition: bool, reason: str) -> None:
    if not condition:
        pytest.skip(f"E2E capability unavailable yet: {reason}")
