"""Revision 202610281000 strips the retired header-logo keys from every stored
theme before ``WidgetTheme`` stops accepting them.

A theme is stored in three places: ``widgets.theme``, a template's draft in
``widget_templates.theme`` and the release inside ``widget_templates.published``.
The model forbids unknown keys, so one key left in any of them makes that row
fail validation on read.
"""

import json
from collections.abc import Generator
from contextlib import closing
from uuid import uuid4

import pytest
from testcontainers.postgres import PostgresContainer

from alembic import command
from tests.integration.migrations import test_file_icon_staged_backfill_expand as expand

cleanup_database = expand.cleanup_database
encryption_service = expand.encryption_service
override_settings_for_session = expand.override_settings_for_session
seed_default_models = expand.seed_default_models

pytestmark = [pytest.mark.integration, pytest.mark.migration_isolation]

PRE_REVISION = "202610271100"
CLEANUP_REVISION = "202610281000"

LOGO = {"logo_url": "https://www.kommun.se/logo.svg", "logo_file_id": None}


@pytest.fixture(scope="module")
def postgres() -> Generator[PostgresContainer, None, None]:
    with PostgresContainer(
        image=expand._POSTGRES_13_IMAGE,
        username="widget_theme",
        password="widget_theme_password",
        dbname="widget_theme",
    ) as container:
        command.upgrade(
            expand._alembic_config(container.get_connection_url()), PRE_REVISION
        )
        yield container


@pytest.fixture
def database(postgres: PostgresContainer) -> Generator[str, None, None]:
    database_url = postgres.get_connection_url()
    try:
        yield database_url
    finally:
        command.downgrade(expand._alembic_config(database_url), PRE_REVISION)


def _execute(database_url: str, query: str, *params) -> list[tuple]:
    connection = expand._connect(database_url)
    connection.autocommit = True
    with closing(connection):
        with connection.cursor() as cursor:
            cursor.execute(query, params)
            return cursor.fetchall() if cursor.description else []


def _seed_tenant_and_space(database_url: str) -> tuple[str, str]:
    tenant_id, space_id = str(uuid4()), str(uuid4())
    _execute(
        database_url,
        "INSERT INTO tenants (id, name, quota_limit, state) "
        "VALUES (%s, %s, 1000000, 'active')",
        tenant_id,
        f"widget-theme-{tenant_id}",
    )
    _execute(
        database_url,
        "INSERT INTO spaces (id, name, tenant_id) VALUES (%s, %s, %s)",
        space_id,
        "Shared",
        tenant_id,
    )
    return tenant_id, space_id


def _insert_widget(
    database_url: str, tenant_id: str, space_id: str, theme: dict
) -> str:
    widget_id = str(uuid4())
    _execute(
        database_url,
        "INSERT INTO widgets (id, public_id, tenant_id, space_id, target_type, "
        "target_id, name, theme) VALUES (%s, %s, %s, %s, 'assistant', %s, %s, %s)",
        widget_id,
        f"wgt_{widget_id[:22]}",
        tenant_id,
        space_id,
        str(uuid4()),
        "Fråga oss",
        json.dumps(theme),
    )
    return widget_id


def _insert_template(
    database_url: str, tenant_id: str, theme: dict, published: dict | None
) -> str:
    template_id = str(uuid4())
    _execute(
        database_url,
        "INSERT INTO widget_templates (id, tenant_id, name, theme, published) "
        "VALUES (%s, %s, %s, %s, %s)",
        template_id,
        tenant_id,
        "Husstil",
        json.dumps(theme),
        json.dumps(published) if published is not None else None,
    )
    return template_id


def _theme(database_url: str, table: str, row_id: str) -> dict:
    return _execute(database_url, f"SELECT theme FROM {table} WHERE id = %s", row_id)[
        0
    ][0]


def _published(database_url: str, template_id: str) -> dict | None:
    return _execute(
        database_url,
        "SELECT published FROM widget_templates WHERE id = %s",
        template_id,
    )[0][0]


def test_upgrade_strips_the_logo_keys_everywhere_a_theme_is_stored(database):
    from eneo.widgets.domain.widget import WidgetTheme

    tenant_id, space_id = _seed_tenant_and_space(database)
    with_logo = _insert_widget(
        database, tenant_id, space_id, {"primary_color": "#ABCDEF", **LOGO}
    )
    without_logo = _insert_widget(
        database, tenant_id, space_id, {"primary_color": "#123456"}
    )
    release = {
        "texts": {"title": "Fråga oss"},
        "theme": {"radius": 4, "header_color": "#112233", **LOGO},
        "persona": {"name": "Sigge"},
        "language": "sv",
        "locked_groups": ["appearance"],
    }
    published_template = _insert_template(
        database, tenant_id, {"radius": 8, **LOGO}, release
    )
    draft_only_template = _insert_template(database, tenant_id, {"radius": 2}, None)

    command.upgrade(expand._alembic_config(database), CLEANUP_REVISION)

    assert _theme(database, "widgets", with_logo) == {"primary_color": "#ABCDEF"}
    assert _theme(database, "widgets", without_logo) == {"primary_color": "#123456"}
    assert _theme(database, "widget_templates", published_template) == {"radius": 8}
    assert _published(database, published_template) == {
        **release,
        "theme": {"radius": 4, "header_color": "#112233"},
    }
    assert _theme(database, "widget_templates", draft_only_template) == {"radius": 2}
    assert _published(database, draft_only_template) is None

    # What the repositories do on every read, now that the model forbids the keys.
    for table, row_id in (
        ("widgets", with_logo),
        ("widgets", without_logo),
        ("widget_templates", published_template),
        ("widget_templates", draft_only_template),
    ):
        WidgetTheme.model_validate(_theme(database, table, row_id))
    WidgetTheme.model_validate(_published(database, published_template)["theme"])


def test_upgrade_leaves_a_release_without_a_theme_alone(database):
    tenant_id, _ = _seed_tenant_and_space(database)
    odd_release = {"texts": {"title": "Fråga oss"}, "language": "sv"}
    template_id = _insert_template(database, tenant_id, {}, odd_release)

    command.upgrade(expand._alembic_config(database), CLEANUP_REVISION)

    assert _published(database, template_id) == odd_release
    assert _theme(database, "widget_templates", template_id) == {}


def test_downgrade_is_a_no_op_that_keeps_the_cleaned_rows(database):
    tenant_id, space_id = _seed_tenant_and_space(database)
    widget_id = _insert_widget(database, tenant_id, space_id, {"radius": 0, **LOGO})
    config = expand._alembic_config(database)

    command.upgrade(config, CLEANUP_REVISION)
    command.downgrade(config, PRE_REVISION)

    assert _theme(database, "widgets", widget_id) == {"radius": 0}
    assert _execute(database, "SELECT version_num FROM alembic_version") == [
        (PRE_REVISION,)
    ]
