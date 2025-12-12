from unittest.mock import MagicMock, patch
from uuid import uuid4

import pytest

from intric.spaces.space_factory import SpaceFactory


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
