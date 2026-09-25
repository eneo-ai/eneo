"""The only fields tenant-admin oversight may return.

Oversight shows configuration and metadata of spaces the administrator is not
a member of; content (documents, questions, answers, file names,
conversations) and credentials must never appear. The promise is published in
the space oversight guide, section "What is never shown"
(frontend/apps/docs-site/src/content/guides/space-oversight.mdx). Each
response model is walked recursively and compared with a frozen list of
dotted field paths, so a new field fails here until it is added on purpose.
"""

import typing
from collections.abc import Iterator
from datetime import date, datetime

import pytest
from pydantic import BaseModel

from eneo.spaces.oversight.oversight_models import (
    AdminSpaceDetail,
    AdminSpaceList,
    AdminSpaceMembers,
)
from eneo.widgets.presentation.widget_models import AdminWidgetReview


def _nested(prefix: str, paths: frozenset[str]) -> frozenset[str]:
    return frozenset(f"{prefix}.{path}" for path in paths)


_CLASSIFICATION = frozenset({"id", "name", "security_level"})
_REF = frozenset({"id", "name"})
_PERSON = frozenset({"id", "name", "email"})
_MODEL = frozenset({"id", "name", "hosting", "org"})
_ADMINS = frozenset(
    {
        "count",
        "manageable",
        "principals",
        *_nested("principals", {"id", "kind", "name"}),
    }
)
_VIEWER_MEMBERSHIP = frozenset(
    {
        "role",
        "direct_role",
        "group_role",
        "via_groups",
        *_nested("via_groups", _REF),
        "oversight_joined_at",
        "joinable_roles",
        "can_leave",
    }
)
_WIDGET_REF = frozenset(
    {
        "id",
        "name",
        "status",
        "assistant",
        *_nested("assistant", _REF),
        "activation_requested_at",
    }
)
# The system prompt ("instructions") is configuration here; attachments are
# a count only.
_ASSISTANT = frozenset(
    {
        "id",
        "name",
        "description",
        "published",
        "is_default",
        "updated_at",
        "completion_model",
        *_nested("completion_model", _MODEL),
        "instructions",
        "knowledge_mode",
        "knowledge",
        *_nested(
            "knowledge",
            {
                "id",
                "name",
                "kind",
                "integration_type",
                "integration_item",
                "from_organization",
            },
        ),
        "attachment_count",
        "mcp_servers",
        *_nested("mcp_servers", _REF),
        "capabilities",
        "insight_enabled",
        "logging_enabled",
        "data_retention_days",
        "widgets",
        *_nested("widgets", _WIDGET_REF),
    }
)
# Document counts and sizes, never titles; whether a login is set, never the
# credential.
_KNOWLEDGE_SOURCE = frozenset(
    {
        "id",
        "name",
        "kind",
        "integration_type",
        "integration_item",
        "item_count",
        "size_bytes",
        "updated_at",
        "website_url",
        "update_interval",
        "requires_login",
        "auto_disabled",
        "used_by",
        *_nested("used_by", _REF),
    }
)

MEMBERS_PATHS = frozenset(
    {
        "users",
        *_nested(
            "users",
            {
                "id",
                "username",
                "email",
                "role",
                "state",
                "is_tenant_admin",
                "oversight_join",
                "oversight_join.joined_at",
                "oversight_join.reason",
            },
        ),
        "groups",
        *_nested("groups", {"id", "name", "role", "user_count"}),
        "member_count",
        "group_count",
        "admins",
        *_nested("admins", _ADMINS),
        "viewer_membership",
        *_nested("viewer_membership", _VIEWER_MEMBERSHIP),
    }
)

LIST_PATHS = frozenset(
    {
        "items",
        *_nested(
            "items",
            {
                "id",
                "name",
                "description",
                "icon_id",
                "created_at",
                "security_classification",
                *_nested("security_classification", _CLASSIFICATION),
                "member_count",
                "group_count",
                "admins",
                *_nested("admins", _ADMINS),
                "resources",
                *_nested(
                    "resources",
                    {"assistants", "apps", "group_chats", "knowledge_sources"},
                ),
                "widgets",
                *_nested(
                    "widgets", {"active", "paused", "draft", "awaiting_activation"}
                ),
                "last_activity",
                "viewer_membership",
                *_nested(
                    "viewer_membership",
                    {"role", "via_group_only", "oversight_joined_at"},
                ),
                "attention",
            },
        ),
        "widget_requests",
        *_nested(
            "widget_requests",
            {
                "widget_id",
                "widget_name",
                "space",
                *_nested("space", _REF),
                "requested_at",
                "requested_by",
                *_nested("requested_by", _PERSON),
            },
        ),
    }
)

DETAIL_PATHS = frozenset(
    {
        "id",
        "name",
        "description",
        "icon_id",
        "created_at",
        "updated_at",
        "security_classification",
        *_nested("security_classification", _CLASSIFICATION),
        "settings",
        *_nested(
            "settings",
            {
                "completion_models",
                *_nested("completion_models", _MODEL),
                "embedding_models",
                *_nested("embedding_models", _MODEL),
                "transcription_models",
                *_nested("transcription_models", _MODEL),
                "mcp_servers",
                *_nested("mcp_servers", _REF),
                "capabilities",
                "data_retention_days",
            },
        ),
        # Coarse and k-suppressed: no timestamps, no per-person figures.
        "usage",
        *_nested(
            "usage",
            {
                "window_days",
                "threshold",
                "suppressed",
                "questions",
                "app_runs",
                "active_users",
                "widget_questions",
                "last_activity",
                "knowledge_bytes",
            },
        ),
        "assistants",
        *_nested("assistants", _ASSISTANT),
        "apps",
        *_nested(
            "apps",
            {
                "id",
                "name",
                "description",
                "published",
                "completion_model",
                *_nested("completion_model", _MODEL),
                "transcription_model",
                *_nested("transcription_model", _MODEL),
                "instructions",
                "data_retention_days",
            },
        ),
        "group_chats",
        *_nested(
            "group_chats",
            {"id", "name", "published", "insight_enabled", "assistant_count"},
        ),
        "knowledge",
        *_nested("knowledge", _KNOWLEDGE_SOURCE),
        "inherited_knowledge_count",
        "widgets",
        *_nested("widgets", _WIDGET_REF),
        "members",
        *_nested("members", MEMBERS_PATHS),
        "attention",
    }
)

# The widget itself is the visitor-facing configuration (WidgetPublic).
_WIDGET_PUBLIC = frozenset(
    {
        "id",
        "public_id",
        "space_id",
        "target_type",
        "target_id",
        "status",
        "token_generation",
        "revision",
        "name",
        "texts",
        *_nested(
            "texts",
            {
                "title",
                "welcome",
                "placeholder",
                "suggested_questions",
                "subtitle",
                "footer_text",
                "footer_link_url",
                "footer_link_label",
            },
        ),
        "theme",
        *_nested(
            "theme",
            {
                "primary_color",
                "color_scheme",
                "position",
                "launcher",
                "radius",
                "header_color",
                "primary_color_dark",
                "header_color_dark",
                "logo_url",
                "logo_file_id",
            },
        ),
        "limits",
        *_nested(
            "limits",
            {
                "messages_per_visitor_10min",
                "messages_per_ip_hour",
                "daily_token_budget",
                "max_question_chars",
                "max_session_turns",
            },
        ),
        "privacy",
        *_nested("privacy", {"retention_days", "store_feedback_text"}),
        "language",
        "allowed_origins",
        "bot_protection",
        "show_sources",
        "show_tool_activity",
        "activation_blockers",
        "template",
        *_nested("template", {"id", "name", "locked_groups"}),
        "created_by_user_id",
        "activated_by_user_id",
        "activated_at",
        "paused_at",
        "activation_requested_at",
        "activation_requested_by_user_id",
        "activation_declined_at",
        "activation_declined_by_user_id",
        "activation_decline_reason",
        "created_at",
        "updated_at",
    }
)

REVIEW_PATHS = frozenset(
    {
        "widget",
        *_nested("widget", _WIDGET_PUBLIC),
        "space",
        *_nested("space", _REF),
        "space_kind",
        "space_security_classification",
        *_nested("space_security_classification", _CLASSIFICATION),
        "target",
        *_nested(
            "target",
            {
                "assistant",
                *_nested("assistant", _ASSISTANT),
                "knowledge",
                *_nested("knowledge", _KNOWLEDGE_SOURCE),
                "visitor_mcp_servers",
                *_nested("visitor_mcp_servers", _REF),
                "visitor_capabilities",
            },
        ),
        "created_by",
        *_nested("created_by", _PERSON),
        "activated_by",
        *_nested("activated_by", _PERSON),
        "activation_requested_by",
        *_nested("activation_requested_by", _PERSON),
        "activation_declined_by",
        *_nested("activation_declined_by", _PERSON),
        "viewer_role",
        "viewer_membership",
        *_nested("viewer_membership", _VIEWER_MEMBERSHIP),
        "usage",
        *_nested(
            "usage",
            {
                "questions_7d",
                "questions_30d",
                "blocked_30d",
                "helpful_30d",
                "unhelpful_30d",
                "last_activity",
            },
        ),
    }
)


def _models_in(annotation: object) -> Iterator[type[BaseModel]]:
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        yield annotation
        return
    for arg in typing.get_args(annotation):
        yield from _models_in(arg)


def field_paths(model: type[BaseModel], prefix: str = "") -> set[str]:
    paths: set[str] = set()
    for name, field in model.model_fields.items():
        path = f"{prefix}{name}"
        paths.add(path)
        for nested in _models_in(field.annotation):
            paths |= field_paths(nested, f"{path}.")
    return paths


@pytest.mark.parametrize(
    ("model", "allowed"),
    [
        (AdminSpaceList, LIST_PATHS),
        (AdminSpaceDetail, DETAIL_PATHS),
        (AdminSpaceMembers, MEMBERS_PATHS),
        (AdminWidgetReview, REVIEW_PATHS),
    ],
    ids=lambda value: getattr(value, "__name__", ""),
)
def test_oversight_responses_return_only_allowlisted_fields(
    model: type[BaseModel], allowed: frozenset[str]
) -> None:
    actual = field_paths(model)
    assert sorted(actual - allowed) == [], (
        "New oversight fields: add them to the allowlist here only if they"
        " are configuration or metadata, never content, and check them"
        " against 'What is never shown' in guides/space-oversight.mdx."
    )
    assert sorted(allowed - actual) == [], "Stale allowlist entries."


# Names that would mean content or a credential had been added.
_FORBIDDEN_LEAVES = frozenset(
    {
        "text",
        "title",
        "question",
        "answer",
        "reasoning",
        "tool_calls",
        "input_text",
        "output_text",
        "feedback_text",
        "transcription",
        "file_name",
        "filename",
        "files",
        "attachments",
        "password",
        "encrypted_auth_password",
        "http_auth_username",
        "env_vars",
        "delta_token",
        "folder_path",
        "drive_id",
        "site_id",
    }
)


@pytest.mark.parametrize(
    "model", [AdminSpaceList, AdminSpaceDetail, AdminSpaceMembers, AdminWidgetReview]
)
def test_no_content_or_credential_field_names(model: type[BaseModel]) -> None:
    paths = field_paths(model)
    if model is AdminWidgetReview:
        # The widget's own heading shown to visitors is configuration.
        paths.discard("widget.texts.title")
    leaves = {path.rsplit(".", 1)[-1] for path in paths}
    assert leaves & _FORBIDDEN_LEAVES == set()


def _annotations(
    model: type[BaseModel], prefix: str = ""
) -> Iterator[tuple[str, object]]:
    for name, field in model.model_fields.items():
        path = f"{prefix}{name}"
        yield path, field.annotation
        for nested in _models_in(field.annotation):
            yield from _annotations(nested, f"{path}.")


def _value_types(annotation: object) -> set[object]:
    """The types a field can hold, without None and Annotated metadata."""
    if typing.get_origin(annotation) is typing.Annotated:
        return _value_types(typing.get_args(annotation)[0])
    args = typing.get_args(annotation)
    if not args:
        return {annotation} - {type(None)}
    return set().union(*(_value_types(arg) for arg in args))


# Times kept to the minute on purpose: the viewer's own join, a join through
# oversight (another administrator's audited action) and a widget activation
# request, which is addressed to the organisation's administrators.
_PRECISE_TIMES = (
    "viewer_membership.oversight_joined_at",
    "oversight_join.joined_at",
    "widget_requests.requested_at",
    "widgets.activation_requested_at",
)


def _precise_times(model: type[BaseModel]) -> list[str]:
    return sorted(
        path
        for path, annotation in _annotations(model)
        if path.rsplit(".", 1)[-1].endswith("_at")
        and not path.endswith(_PRECISE_TIMES)
        and _value_types(annotation) != {date}
    )


@pytest.mark.parametrize("model", [AdminSpaceList, AdminSpaceDetail, AdminSpaceMembers])
def test_times_are_days(model: type[BaseModel]) -> None:
    """When something was created or changed is given to the day: in a
    one-person space the time of day would show when that person worked."""
    assert _precise_times(model) == []


def test_a_new_precise_time_is_caught() -> None:
    """Negative control: a new time field, however deep, must be a day."""

    class LeakyMembers(AdminSpaceMembers):
        archived_at: datetime

    class LeakyDetail(AdminSpaceDetail):
        members: LeakyMembers

    assert _precise_times(LeakyDetail) == ["members.archived_at"]


def test_the_walk_catches_a_new_nested_field() -> None:
    """Negative control: a field added deep inside a response is reported."""

    class LeakyMembers(AdminSpaceMembers):
        secret: str

    class LeakyDetail(AdminSpaceDetail):
        members: LeakyMembers

    assert field_paths(LeakyDetail) - DETAIL_PATHS == {"members.secret"}
