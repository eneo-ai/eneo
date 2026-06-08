import logging
from types import SimpleNamespace
from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest
from pydantic import BaseModel, ValidationError

from intric.spaces import space_factory
from intric.spaces.space_factory import SpaceFactory, _build_or_skip


@pytest.fixture
def patched_logger(monkeypatch):
    """Project's `SimpleLogger` (intric.main.logging) bypasses the root
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
