"""Move API key notification state from JSON blobs to relational tables.

Revision ID: api_key_notifications_rel_001
Revises: svc_api_keys_001
Create Date: 2026-04-08 17:00:00.000000
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any
from uuid import UUID

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "api_key_notifications_rel_001"
down_revision = "svc_api_keys_001"
branch_labels = None
depends_on = None

_TENANTS = sa.table(
    "tenants",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("api_key_policy", postgresql.JSONB(astext_type=sa.Text())),
)
_SETTINGS = sa.table(
    "settings",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("user_id", postgresql.UUID(as_uuid=True)),
    sa.column("chatbot_widget", postgresql.JSONB(astext_type=sa.Text())),
    sa.column("updated_at", sa.TIMESTAMP(timezone=True)),
)
_PREFERENCES = sa.table(
    "api_key_notification_preferences",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("user_id", postgresql.UUID(as_uuid=True)),
    sa.column("enabled", sa.Boolean()),
    sa.column("days_before_expiry", sa.Integer()),
    sa.column("auto_follow_published_assistants", sa.Boolean()),
    sa.column("auto_follow_published_apps", sa.Boolean()),
)
_SUBSCRIPTIONS = sa.table(
    "api_key_notification_subscriptions",
    sa.column("id", postgresql.UUID(as_uuid=True)),
    sa.column("user_id", postgresql.UUID(as_uuid=True)),
    sa.column("target_type", sa.Text()),
    sa.column("target_id", postgresql.UUID(as_uuid=True)),
    sa.column("source", sa.Text()),
)


def _as_json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    return {}


def _as_json_list(value: Any) -> list[Any]:
    if isinstance(value, list):
        return list(value)
    return []


def _coerce_day_value(raw: Any, *, default: int | None = None) -> int | None:
    if isinstance(raw, bool):
        return default
    if isinstance(raw, int):
        return raw if raw > 0 else default
    if isinstance(raw, float):
        if raw.is_integer() and raw > 0:
            return int(raw)
        return default
    if isinstance(raw, str):
        try:
            parsed = int(raw.strip())
        except (AttributeError, TypeError, ValueError):
            return default
        return parsed if parsed > 0 else default
    if isinstance(raw, list):
        candidates = [
            value for value in (_coerce_day_value(item) for item in raw) if value
        ]
        return max(candidates) if candidates else default
    return default


def _normalize_notification_policy(raw_policy: Any) -> dict[str, Any] | None:
    if not isinstance(raw_policy, dict):
        return None

    updated_policy = dict(raw_policy)
    notification_policy = updated_policy.get("notification_policy")
    if not isinstance(notification_policy, dict):
        return updated_policy

    normalized_notification_policy = dict(notification_policy)
    max_days = _coerce_day_value(
        normalized_notification_policy.get("max_days_before_expiry")
    )
    if max_days is None:
        normalized_notification_policy.pop("max_days_before_expiry", None)
    else:
        normalized_notification_policy["max_days_before_expiry"] = max_days

    default_days = _coerce_day_value(
        normalized_notification_policy.get("default_days_before_expiry"),
        default=30,
    )
    if default_days is None:
        default_days = 30
    if max_days is not None:
        default_days = min(default_days, max_days)
    normalized_notification_policy["default_days_before_expiry"] = default_days
    updated_policy["notification_policy"] = normalized_notification_policy
    return updated_policy


def _normalize_subscriptions(raw_items: Any) -> list[dict[str, Any]]:
    deduped: dict[tuple[str, UUID], dict[str, Any]] = {}
    for raw_item in _as_json_list(raw_items):
        item = _as_json_object(raw_item)
        raw_target_type = item.get("target_type")
        raw_target_id = item.get("target_id")
        if raw_target_type not in {"key", "assistant", "app", "space"}:
            continue
        if isinstance(raw_target_id, UUID):
            target_id = raw_target_id
        elif isinstance(raw_target_id, str):
            try:
                target_id = UUID(raw_target_id)
            except ValueError:
                continue
        else:
            continue
        deduped[(str(raw_target_type), target_id)] = {
            "target_type": str(raw_target_type),
            "target_id": target_id,
        }

    return list(deduped.values())


def upgrade() -> None:
    op.create_table(
        "api_key_notification_preferences",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column(
            "days_before_expiry",
            sa.Integer(),
            nullable=False,
            server_default="30",
        ),
        sa.Column(
            "auto_follow_published_assistants",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.Column(
            "auto_follow_published_apps",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
        sa.CheckConstraint(
            "days_before_expiry > 0",
            name="ck_api_key_notification_preferences_days_positive",
        ),
    )
    op.create_index(
        op.f("ix_api_key_notification_preferences_user_id"),
        "api_key_notification_preferences",
        ["user_id"],
        unique=True,
    )

    op.create_table(
        "api_key_notification_subscriptions",
        sa.Column(
            "id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.TIMESTAMP(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "user_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("target_type", sa.Text(), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("source", sa.Text(), nullable=False, server_default="manual"),
        sa.CheckConstraint(
            "target_type IN ('key', 'assistant', 'app', 'space')",
            name="ck_api_key_notification_subscriptions_target_type",
        ),
        sa.CheckConstraint(
            "source IN ('manual', 'auto_follow')",
            name="ck_api_key_notification_subscriptions_source",
        ),
        sa.UniqueConstraint(
            "user_id",
            "target_type",
            "target_id",
            name="uq_api_key_notification_subscription_user_target",
        ),
    )
    op.create_index(
        op.f("ix_api_key_notification_subscriptions_user_id"),
        "api_key_notification_subscriptions",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_api_key_notification_subscriptions_target_id"),
        "api_key_notification_subscriptions",
        ["target_id"],
        unique=False,
    )

    bind = op.get_bind()

    tenant_rows = bind.execute(
        sa.select(_TENANTS.c.id, _TENANTS.c.api_key_policy)
    ).all()
    for tenant_id, api_key_policy in tenant_rows:
        normalized_policy = _normalize_notification_policy(api_key_policy)
        if normalized_policy is not None and normalized_policy != api_key_policy:
            bind.execute(
                sa.update(_TENANTS)
                .where(_TENANTS.c.id == tenant_id)
                .values(api_key_policy=normalized_policy)
            )

    settings_rows = bind.execute(
        sa.select(
            _SETTINGS.c.id,
            _SETTINGS.c.user_id,
            _SETTINGS.c.chatbot_widget,
            _SETTINGS.c.updated_at,
        ).order_by(_SETTINGS.c.user_id.asc(), _SETTINGS.c.updated_at.desc())
    ).all()

    migrated_users: set[Any] = set()
    for settings_id, user_id, chatbot_widget, _updated_at in settings_rows:
        widget = _as_json_object(chatbot_widget)
        bucket = _as_json_object(widget.get("api_key_notifications"))

        if user_id is not None and user_id not in migrated_users and bucket:
            preferences = _as_json_object(bucket.get("preferences"))
            if preferences:
                bind.execute(
                    sa.insert(_PREFERENCES).values(
                        user_id=user_id,
                        enabled=bool(preferences.get("enabled")),
                        days_before_expiry=_coerce_day_value(
                            preferences.get("days_before_expiry"),
                            default=30,
                        )
                        or 30,
                        auto_follow_published_assistants=bool(
                            preferences.get("auto_follow_published_assistants")
                        ),
                        auto_follow_published_apps=bool(
                            preferences.get("auto_follow_published_apps")
                        ),
                    )
                )

            for subscription in _normalize_subscriptions(bucket.get("subscriptions")):
                bind.execute(
                    sa.insert(_SUBSCRIPTIONS).values(
                        user_id=user_id,
                        target_type=subscription["target_type"],
                        target_id=subscription["target_id"],
                        source="manual",
                    )
                )

            migrated_users.add(user_id)

        if "api_key_notifications" in widget:
            widget.pop("api_key_notifications", None)
            bind.execute(
                sa.update(_SETTINGS)
                .where(_SETTINGS.c.id == settings_id)
                .values(chatbot_widget=widget)
            )


def downgrade() -> None:
    bind = op.get_bind()

    tenant_rows = bind.execute(
        sa.select(_TENANTS.c.id, _TENANTS.c.api_key_policy)
    ).all()
    for tenant_id, api_key_policy in tenant_rows:
        tenant_policy = _as_json_object(api_key_policy)
        notification_policy = _as_json_object(tenant_policy.get("notification_policy"))
        if not notification_policy:
            continue
        default_days = _coerce_day_value(
            notification_policy.get("default_days_before_expiry")
        )
        if default_days is None:
            continue
        notification_policy["default_days_before_expiry"] = [default_days]
        tenant_policy["notification_policy"] = notification_policy
        bind.execute(
            sa.update(_TENANTS)
            .where(_TENANTS.c.id == tenant_id)
            .values(api_key_policy=tenant_policy)
        )

    settings_by_user: dict[Any, tuple[Any, dict[str, Any]]] = {}
    settings_rows = bind.execute(
        sa.select(
            _SETTINGS.c.id,
            _SETTINGS.c.user_id,
            _SETTINGS.c.chatbot_widget,
            _SETTINGS.c.updated_at,
        ).order_by(_SETTINGS.c.user_id.asc(), _SETTINGS.c.updated_at.desc())
    ).all()
    for settings_id, user_id, chatbot_widget, _updated_at in settings_rows:
        if user_id is None or user_id in settings_by_user:
            continue
        settings_by_user[user_id] = (settings_id, _as_json_object(chatbot_widget))

    preferences_rows = bind.execute(
        sa.select(
            _PREFERENCES.c.user_id,
            _PREFERENCES.c.enabled,
            _PREFERENCES.c.days_before_expiry,
            _PREFERENCES.c.auto_follow_published_assistants,
            _PREFERENCES.c.auto_follow_published_apps,
        )
    ).all()
    subscriptions_rows = bind.execute(
        sa.select(
            _SUBSCRIPTIONS.c.user_id,
            _SUBSCRIPTIONS.c.target_type,
            _SUBSCRIPTIONS.c.target_id,
        )
    ).all()

    subscriptions_by_user: dict[Any, list[dict[str, Any]]] = defaultdict(list)
    for user_id, target_type, target_id in subscriptions_rows:
        subscriptions_by_user[user_id].append(
            {"target_type": target_type, "target_id": str(target_id)}
        )

    for (
        user_id,
        enabled,
        days_before_expiry,
        auto_follow_published_assistants,
        auto_follow_published_apps,
    ) in preferences_rows:
        settings_info = settings_by_user.get(user_id)
        if settings_info is None:
            insert_result = bind.execute(
                sa.insert(_SETTINGS)
                .values(
                    user_id=user_id,
                    chatbot_widget={},
                )
                .returning(_SETTINGS.c.id)
            )
            settings_id = insert_result.scalar_one()
            widget: dict[str, Any] = {}
            settings_by_user[user_id] = (settings_id, widget)
        else:
            settings_id, widget = settings_info

        widget = dict(widget)
        widget["api_key_notifications"] = {
            "preferences": {
                "enabled": enabled,
                "days_before_expiry": [days_before_expiry],
                "auto_follow_published_assistants": auto_follow_published_assistants,
                "auto_follow_published_apps": auto_follow_published_apps,
            },
            "subscriptions": subscriptions_by_user.get(user_id, []),
        }
        bind.execute(
            sa.update(_SETTINGS)
            .where(_SETTINGS.c.id == settings_id)
            .values(chatbot_widget=widget)
        )

    op.drop_index(
        op.f("ix_api_key_notification_subscriptions_target_id"),
        table_name="api_key_notification_subscriptions",
    )
    op.drop_index(
        op.f("ix_api_key_notification_subscriptions_user_id"),
        table_name="api_key_notification_subscriptions",
    )
    op.drop_table("api_key_notification_subscriptions")
    op.drop_index(
        op.f("ix_api_key_notification_preferences_user_id"),
        table_name="api_key_notification_preferences",
    )
    op.drop_table("api_key_notification_preferences")
