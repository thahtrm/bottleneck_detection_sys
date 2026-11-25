from __future__ import annotations

from .auth import (
    E2E_ACCOUNTS,
    E2EAccountSpec,
    create_e2e_user,
    ensure_e2e_project,
    login_as,
    mint_session_cookie,
    quick_switch,
    seed_e2e_accounts,
)
from .capabilities import (
    get_local_jira_client_cls,
    has_column,
    has_local_jira_client,
    has_route,
    has_setting,
    has_table,
    require_capability,
    supported_member_roles,
    supports_member_role,
)
from .contracts import (
    assert_canonical_link,
    assert_change_recorded,
    assert_jira_v3_issue_raw,
    assert_risk_state_fresh,
)
from .db import build_cli_env, make_e2e_paths, make_e2e_settings, run_erw_cli
from .jira_mock import FakeJira, MockJiraCloudServer, make_minimal_v3_issue
from .sample_files import (
    make_empty_attachment,
    make_oversized_attachment,
    make_path_traversal_attachment,
    make_png_attachment,
    make_text_attachment,
)

__all__ = [
    "E2E_ACCOUNTS",
    "E2EAccountSpec",
    "FakeJira",
    "MockJiraCloudServer",
    "assert_canonical_link",
    "assert_change_recorded",
    "assert_jira_v3_issue_raw",
    "assert_risk_state_fresh",
    "build_cli_env",
    "create_e2e_user",
    "ensure_e2e_project",
    "get_local_jira_client_cls",
    "has_column",
    "has_local_jira_client",
    "has_route",
    "has_setting",
    "has_table",
    "login_as",
    "make_e2e_paths",
    "make_e2e_settings",
    "make_empty_attachment",
    "make_minimal_v3_issue",
    "make_oversized_attachment",
    "make_path_traversal_attachment",
    "make_png_attachment",
    "make_text_attachment",
    "mint_session_cookie",
    "quick_switch",
    "require_capability",
    "run_erw_cli",
    "seed_e2e_accounts",
    "supported_member_roles",
    "supports_member_role",
]
