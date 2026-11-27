import logging
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from eneo.completion_models.domain.model_kwargs_capabilities import (
    ModelKwargCapability,
    SupportedModelKwargs,
)
from eneo.spaces import space_factory
from eneo.spaces.space_factory import SpaceFactory, _build_or_skip


@pytest.fixture
def patched_logger(monkeypatch):
    """Project's `SimpleLogger` (eneo.main.logging) bypasses the root
    `logging.Logger.manager.loggerDict`, so pytest's `caplog` can't intercept
    its records via propagation. Swap in a stdlib logger for log assertions."""
    test_logger = logging.getLogger("test_space_factory_build_or_skip")
    test_logger.handlers = []
    monkeypatch.setattr(space_factory, "logger", test_logger)
    return test_logger


class _Domain(BaseModel):
    """Trivial Pydantic model for exercising `_build_or_skip` in isolation."""

    name: str


def _row(id_=None, tenant_id=None, user_id=None, space_id=None, name="ok"):
    """Mimics the attribute shape of a SQLAlchemy row that `_build_or_skip`
    introspects for its log payload. SimpleNamespace (not MagicMock) so that
    `row.name` is the literal string we set, not an auto-attribute mock."""
    return SimpleNamespace(
        id=id_ if id_ is not None else uuid4(),
        tenant_id=tenant_id if tenant_id is not None else uuid4(),
        user_id=user_id if user_id is not None else uuid4(),
        space_id=space_id if space_id is not None else uuid4(),
        name=name,
    )


def _build_good(row):
    return _Domain(name=row.name)


def _build_bad(_row):
    # Force a Pydantic ValidationError without going through the DB.
    raise ValidationError.from_exception_data(
        title="ValidationError",
        line_errors=[
            {
                "type": "missing",
                "loc": ("name",),
                "input": None,
            }
        ],
    )


def test_build_or_skip_returns_all_when_all_rows_valid():
    rows = [_row(), _row(), _row()]

    out = _build_or_skip(rows, item_kind="thing", build_fn=_build_good)

    assert len(out) == 3


def test_build_or_skip_skips_invalid_row_and_logs(caplog, patched_logger):
    """One bad row must not abort loading the rest of the space, and the
    skip must be observable in logs."""
    bad_id = uuid4()
    rows = [_row(), _row(id_=bad_id), _row()]

    def build_fn(row):
        if row.id == bad_id:
            return _build_bad(row)
        return _build_good(row)

    with caplog.at_level(logging.ERROR, logger=patched_logger.name):
        out = _build_or_skip(rows, item_kind="service", build_fn=build_fn)

    assert len(out) == 2

    matching = [r for r in caplog.records if "Skipping invalid" in r.getMessage()]
    assert len(matching) == 1

    # Log keys are part of the contract — dashboards / alerts query them
    # by name. Keep them stable across item kinds.
    record = matching[0]
    assert getattr(record, "space_item_kind", None) == "service"
    assert getattr(record, "space_item_id", None) == bad_id
    assert getattr(record, "validation_error_count", None) == 1


def test_build_or_skip_propagates_non_validation_errors():
    """Anything that isn't a ValidationError is a real bug, not data drift —
    the helper must not swallow it."""

    def boom(_row):
        raise RuntimeError("genuine bug")

    with pytest.raises(RuntimeError, match="genuine bug"):
        _build_or_skip([_row()], item_kind="service", build_fn=boom)


def test_build_or_skip_log_payload_redacts_pydantic_input(caplog, patched_logger):
    """Pydantic errors carry an `input` field that can echo row contents
    (prompts, tenant data). The helper must call `errors(include_input=False,
    include_url=False)` so logs don't leak that payload."""

    def build_fn(_row):
        raise ValidationError.from_exception_data(
            title="ValidationError",
            line_errors=[
                {
                    "type": "missing",
                    "loc": ("name",),
                    "input": {"sensitive_prompt": "do not log this"},
                }
            ],
        )

    with caplog.at_level(logging.ERROR, logger=patched_logger.name):
        _build_or_skip([_row()], item_kind="service", build_fn=build_fn)

    record = next(r for r in caplog.records if "Skipping invalid" in r.getMessage())
    errors = getattr(record, "validation_errors")
    assert errors and "input" not in errors[0]
    assert "url" not in errors[0]


@pytest.fixture
def factory():
    return SpaceFactory(MagicMock(), MagicMock())


def test_create_space_from_request():
    name = "test space"
    created_space = SpaceFactory.create_space(name=name, tenant_id=uuid4())

    assert created_space.id is None
    assert created_space.name == name
    assert created_space.description is None
    assert created_space.embedding_models == []
    assert created_space.completion_models == []
    assert created_space.tenant_id is not None
    assert created_space.members == {}


def test_create_applications_projection_preserves_sparse_response_contract(factory):
    now = datetime.now(UTC)
    space_id = uuid4()
    user_id = uuid4()
    member_id = uuid4()
    group_id = uuid4()
    completion_model_id = uuid4()
    default_assistant_id = uuid4()
    assistant_id = uuid4()
    missing_model_assistant_id = uuid4()
    invalid_assistant_id = uuid4()
    app_id = uuid4()
    group_chat_ids = [uuid4(), uuid4()]
    service_ids = [uuid4(), uuid4()]

    space_in_db = MagicMock()
    space_in_db.id = space_id
    space_in_db.user_id = None
    space_in_db.tenant_space_id = uuid4()

    completion_model = MagicMock()
    completion_model.id = completion_model_id
    completion_model.is_deprecated = True
    completion_model.get_supported_model_kwargs.return_value = SupportedModelKwargs(
        temperature=ModelKwargCapability(supported=True)
    )

    def assistant(
        *,
        id,
        is_default=False,
        model_id=completion_model_id,
        kwargs=None,
    ):
        row = MagicMock()
        row.id = id
        row.created_at = now
        row.updated_at = now
        row.name = f"assistant-{id}"
        row.completion_model_kwargs = kwargs
        row.logging_enabled = True
        row.user_id = user_id
        row.published = True
        row.description = None
        row.metadata_json = None
        row.icon_id = None
        row.completion_model_id = model_id
        row.insight_enabled = False
        row.is_default = is_default
        return row

    default_assistant = assistant(id=default_assistant_id, is_default=True)
    supported_assistant = assistant(
        id=assistant_id,
        kwargs={"temperature": 0.4, "top_p": 0.8},
    )
    missing_model_assistant = assistant(
        id=missing_model_assistant_id,
        model_id=uuid4(),
        kwargs=None,
    )
    invalid_assistant = assistant(
        id=invalid_assistant_id,
        kwargs={"temperature": "not-a-number"},
    )

    app = MagicMock()
    app.id = app_id
    app.created_at = now
    app.updated_at = now
    app.name = "app"
    app.description = None
    app.published = True
    app.user_id = user_id
    app.icon_id = None
    # The Applications response deliberately ignores aggregate-only app state.
    # Corruption there must not force full-domain hydration or hide metadata.
    app.completion_model_kwargs = {"temperature": "not-a-number"}

    group_chats = []
    for group_chat_id in group_chat_ids:
        group_chat = MagicMock()
        group_chat.id = group_chat_id
        group_chat.created_at = now
        group_chat.updated_at = now
        group_chat.name = f"group-chat-{group_chat_id}"
        group_chat.user_id = user_id
        group_chat.published = True
        group_chat.metadata_json = None
        group_chat.icon_id = None
        group_chat.insight_enabled = False
        group_chats.append(group_chat)

    services = []
    for service_id in service_ids:
        service = MagicMock()
        service.id = service_id
        service.created_at = now
        service.updated_at = now
        service.name = f"service-{service_id}"
        service.prompt = ""
        service.completion_model_kwargs = None
        service.user_id = user_id
        services.append(service)

    projection = factory.create_applications_projection(
        space_in_db=space_in_db,
        member_roles={member_id: "admin"},
        group_member_roles={group_id: "viewer"},
        assistants_in_db=[
            default_assistant,
            supported_assistant,
            missing_model_assistant,
            invalid_assistant,
        ],
        group_chats_in_db=group_chats,
        apps_in_db=[app],
        services_in_db=services,
        completion_models=[completion_model],
    )

    assert [item.id for item in projection.assistants] == [
        assistant_id,
        missing_model_assistant_id,
    ]
    assert projection.assistants[0].completion_model_id == completion_model_id
    assert projection.assistants[0].completion_model_kwargs.temperature == 0.4
    assert projection.assistants[0].completion_model_kwargs.top_p is None
    assert projection.assistants[1].completion_model_id is None
    assert (
        projection.assistants[1].completion_model_kwargs.model_dump(exclude_none=True)
        == {}
    )
    assert projection.access.default_assistant_id == default_assistant_id
    assert projection.access.assistant_ids == frozenset(
        {assistant_id, missing_model_assistant_id}
    )
    assert projection.access.app_ids == frozenset({app_id})
    assert projection.access.members[member_id].role == "admin"
    assert projection.access.group_members[group_id].role == "viewer"
    assert [item.id for item in projection.group_chats] == group_chat_ids
    assert [item.id for item in projection.services] == service_ids


def test_create_space_from_db_maps_integration_knowledge_fields(factory):
    """Test that integration knowledge fields including resource_type and drive_id are mapped."""
    space_id = uuid4()
    tenant_id = uuid4()
    embedding_model_id = uuid4()

    # Create mock space_in_db
    space_in_db = MagicMock()
    space_in_db.id = space_id
    space_in_db.tenant_id = tenant_id
    space_in_db.tenant_space_id = None
    space_in_db.user_id = None
    space_in_db.name = "Test Space"
    space_in_db.description = "Test Description"
    space_in_db.created_at = None
    space_in_db.updated_at = None
    space_in_db.members = []
    space_in_db.completion_models_mapping = []
    space_in_db.transcription_models_mapping = []
    space_in_db.embedding_models_mapping = []

    # Create mock integration knowledge with OneDrive fields
    ik_mock = MagicMock()
    ik_mock.id = uuid4()
    ik_mock.name = "OneDrive Documents"
    ik_mock.original_name = "My OneDrive"
    ik_mock.url = "https://onedrive.example.com"
    ik_mock.tenant_id = tenant_id
    ik_mock.space_id = space_id
    ik_mock.embedding_model_id = embedding_model_id
    ik_mock.size = 1024
    ik_mock.site_id = None
    ik_mock.last_synced_at = None
    ik_mock.last_sync_summary = None
    ik_mock.sharepoint_subscription_id = None
    ik_mock.delta_token = None
    ik_mock.folder_id = "folder-123"
    ik_mock.folder_path = "/Documents"
    ik_mock.selected_item_type = "folder"
    ik_mock.resource_type = "onedrive"
    ik_mock.drive_id = "drive-abc-123"
    ik_mock.user_integration = MagicMock()

    space_in_db.integration_knowledge_list = [ik_mock]

    # Create mock embedding model
    embedding_model = MagicMock()
    embedding_model.id = embedding_model_id
    embedding_model.is_deprecated = False

    # Create mock user
    user = MagicMock()
    user.id = uuid4()

    # Patch sqlalchemy inspect to avoid issues with mock objects
    with patch("sqlalchemy.inspect") as mock_inspect:
        mock_insp = MagicMock()
        mock_insp.unloaded = {"sharepoint_subscription"}
        mock_inspect.return_value = mock_insp

        space = factory.create_space_from_db(
            space_in_db=space_in_db,
            user=user,
            embedding_models=[embedding_model],
        )

    # Verify integration knowledge was created with all fields
    assert len(space.integration_knowledge_list) == 1
    ik = space.integration_knowledge_list[0]

    assert ik.name == "OneDrive Documents"
    assert ik.original_name == "My OneDrive"
    assert ik.resource_type == "onedrive"
    assert ik.drive_id == "drive-abc-123"
    assert ik.folder_id == "folder-123"
    assert ik.folder_path == "/Documents"
    assert ik.selected_item_type == "folder"


def test_create_space_from_db_maps_sharepoint_integration_knowledge(factory):
    """Test that SharePoint integration knowledge fields are mapped correctly."""
    space_id = uuid4()
    tenant_id = uuid4()
    embedding_model_id = uuid4()

    # Create mock space_in_db
    space_in_db = MagicMock()
    space_in_db.id = space_id
    space_in_db.tenant_id = tenant_id
    space_in_db.tenant_space_id = None
    space_in_db.user_id = None
    space_in_db.name = "Test Space"
    space_in_db.description = None
    space_in_db.created_at = None
    space_in_db.updated_at = None
    space_in_db.members = []
    space_in_db.completion_models_mapping = []
    space_in_db.transcription_models_mapping = []
    space_in_db.embedding_models_mapping = []

    # Create mock SharePoint integration knowledge
    ik_mock = MagicMock()
    ik_mock.id = uuid4()
    ik_mock.name = "SharePoint Site"
    ik_mock.original_name = "Corporate Documents"
    ik_mock.url = "https://sharepoint.example.com/sites/corporate"
    ik_mock.tenant_id = tenant_id
    ik_mock.space_id = space_id
    ik_mock.embedding_model_id = embedding_model_id
    ik_mock.size = 2048
    ik_mock.site_id = "site-xyz-789"
    ik_mock.last_synced_at = None
    ik_mock.last_sync_summary = None
    ik_mock.sharepoint_subscription_id = uuid4()
    ik_mock.delta_token = "delta-token-123"
    ik_mock.folder_id = None
    ik_mock.folder_path = None
    ik_mock.selected_item_type = "site_root"
    ik_mock.resource_type = "site"
    ik_mock.drive_id = None
    ik_mock.user_integration = MagicMock()

    space_in_db.integration_knowledge_list = [ik_mock]

    # Create mock embedding model
    embedding_model = MagicMock()
    embedding_model.id = embedding_model_id
    embedding_model.is_deprecated = False

    # Create mock user
    user = MagicMock()
    user.id = uuid4()

    # Patch sqlalchemy inspect to avoid issues with mock objects
    with patch("sqlalchemy.inspect") as mock_inspect:
        mock_insp = MagicMock()
        mock_insp.unloaded = {"sharepoint_subscription"}
        mock_inspect.return_value = mock_insp

        space = factory.create_space_from_db(
            space_in_db=space_in_db,
            user=user,
            embedding_models=[embedding_model],
        )

    # Verify SharePoint integration knowledge was created with all fields
    assert len(space.integration_knowledge_list) == 1
    ik = space.integration_knowledge_list[0]

    assert ik.name == "SharePoint Site"
    assert ik.original_name == "Corporate Documents"
    assert ik.resource_type == "site"
    assert ik.drive_id is None
    assert ik.site_id == "site-xyz-789"
    assert ik.delta_token == "delta-token-123"
    assert ik.selected_item_type == "site_root"
