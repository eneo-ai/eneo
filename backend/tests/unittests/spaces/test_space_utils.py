"""Unit tests for space_utils - organization knowledge accessibility.

These tests ensure that child spaces (personal and shared) can access
knowledge (collections, websites, integrations) from their parent org space.
"""

from uuid import uuid4

import pytest

from intric.spaces.space import Space
from intric.spaces.utils.space_utils import effective_space_ids


@pytest.fixture
def org_space_id():
    """ID of the organization space."""
    return uuid4()


@pytest.fixture
def org_space(org_space_id):
    """An organization space (no parent, no user)."""
    return Space(
        id=org_space_id,
        tenant_id=uuid4(),
        tenant_space_id=None,  # Org space has no parent
        user_id=None,  # Org space has no user
        name="Organization space",
        description="Shared knowledge for the tenant",
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        mcp_servers=[],
        default_assistant=None,
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
    )


@pytest.fixture
def shared_space(org_space_id):
    """A shared space (child of org space)."""
    return Space(
        id=uuid4(),
        tenant_id=uuid4(),
        tenant_space_id=org_space_id,  # Points to parent org space
        user_id=None,  # Shared space has no user
        name="Team space",
        description="A shared team space",
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        mcp_servers=[],
        default_assistant=None,
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
    )


@pytest.fixture
def personal_space(org_space_id):
    """A personal space (child of org space, owned by user)."""
    return Space(
        id=uuid4(),
        tenant_id=uuid4(),
        tenant_space_id=org_space_id,  # Points to parent org space
        user_id=uuid4(),  # Personal space has a user
        name="User's personal space",
        description=None,
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        mcp_servers=[],
        default_assistant=None,
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
    )


class TestEffectiveSpaceIds:
    """Tests for effective_space_ids() function.

    This function determines which space IDs to query when fetching knowledge
    (collections, websites, integration knowledge) for a space.

    The key behavior is that child spaces (shared and personal) should be able
    to access knowledge from their parent org space.
    """

    def test_org_space_returns_only_own_id(self, org_space):
        """Org space should only return its own ID."""
        result = effective_space_ids(org_space)

        assert result == [org_space.id]

    def test_shared_space_includes_org_space_id(self, shared_space, org_space_id):
        """Shared space should include both own ID and parent org space ID.

        This allows shared spaces to access org-level knowledge (collections,
        websites, integrations) without needing junction table records.
        """
        result = effective_space_ids(shared_space)

        assert len(result) == 2
        assert shared_space.id in result
        assert org_space_id in result

    def test_personal_space_includes_org_space_id(self, personal_space, org_space_id):
        """Personal space should include both own ID and parent org space ID.

        This allows personal spaces to access org-level knowledge (collections,
        websites, integrations) without needing junction table records.
        """
        result = effective_space_ids(personal_space)

        assert len(result) == 2
        assert personal_space.id in result
        assert org_space_id in result

    def test_child_space_own_id_comes_first(self, shared_space, org_space_id):
        """Child space's own ID should come first in the list.

        This ensures that space-specific knowledge takes precedence in queries.
        """
        result = effective_space_ids(shared_space)

        assert result[0] == shared_space.id
        assert result[1] == org_space_id


class TestOrgKnowledgeAccessibility:
    """Integration-style tests documenting expected knowledge accessibility behavior.

    These tests document the expected behavior for how organization-level
    knowledge should be accessible from child spaces.
    """

    def test_shared_space_can_query_org_collections(self, shared_space, org_space_id):
        """Shared spaces should be able to query collections from org space.

        When querying collections with effective_space_ids(), the query should
        find collections where space_id IN [shared_space.id, org_space_id].
        """
        space_ids = effective_space_ids(shared_space)

        # Simulating: SELECT * FROM collections WHERE space_id IN (space_ids)
        # This should find collections belonging to either the shared space
        # or the org space
        assert org_space_id in space_ids
        assert shared_space.id in space_ids

    def test_shared_space_can_query_org_websites(self, shared_space, org_space_id):
        """Shared spaces should be able to query websites from org space."""
        space_ids = effective_space_ids(shared_space)

        assert org_space_id in space_ids

    def test_shared_space_can_query_org_integration_knowledge(
        self, shared_space, org_space_id
    ):
        """Shared spaces should be able to query integration knowledge from org space."""
        space_ids = effective_space_ids(shared_space)

        assert org_space_id in space_ids

    def test_personal_space_can_query_org_knowledge(self, personal_space, org_space_id):
        """Personal spaces should be able to query all knowledge types from org space."""
        space_ids = effective_space_ids(personal_space)

        assert org_space_id in space_ids
        assert personal_space.id in space_ids
