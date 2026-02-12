"""
Unit tests for Integration Knowledge Permissions and Access Control.

Tests cover:
- Role-based access control for organization knowledge
- Permission enforcement (create, read, delete)
- VIEWER, EDITOR, ADMIN permission differences
"""
import pytest
from sqlalchemy import select

from intric.spaces.space import Space
from intric.actors.actors.space_actor import SpaceActor
from intric.database.tables.spaces_table import Spaces, SpacesUsers
from intric.spaces.api.space_models import SpaceRoleValue


def _space_from_db(db_space: Spaces) -> Space:
    """Convert database Spaces model to Space domain entity (minimal)."""
    return Space(
        id=db_space.id,
        tenant_id=db_space.tenant_id,
        user_id=db_space.user_id,
        tenant_space_id=db_space.tenant_space_id,
        name=db_space.name,
        description=db_space.description,
        embedding_models=[],
        completion_models=[],
        transcription_models=[],
        default_assistant=None,
        assistants=[],
        apps=[],
        services=[],
        websites=[],
        collections=[],
        integration_knowledge_list=[],
        members={},
    )


class TestOrganizationKnowledgePermissions:
    """Test permissions for organization space knowledge operations."""

    @pytest.mark.skip(reason="Requires database fixtures - not a unit test")
    async def test_only_org_admin_can_create_knowledge(
        self, db_container, tenant_factory, user_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify only ADMIN role can create knowledge on org space."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create users with different roles
            admin_user = await user_factory(session, tenant_id=tenant.id)
            editor_user = await user_factory(session, tenant_id=tenant.id)
            viewer_user = await user_factory(session, tenant_id=tenant.id)

            # Create org space
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            # Assign roles
            admin_member = SpacesUsers(
                space_id=org_space.id,
                user_id=admin_user.id,
                role=SpaceRoleValue.ADMIN,
            )
            editor_member = SpacesUsers(
                space_id=org_space.id,
                user_id=editor_user.id,
                role=SpaceRoleValue.EDITOR,
            )
            viewer_member = SpacesUsers(
                space_id=org_space.id,
                user_id=viewer_user.id,
                role=SpaceRoleValue.VIEWER,
            )
            session.add(admin_member)
            session.add(editor_member)
            session.add(viewer_member)
            await session.flush()

            # Reload space for each user to get their specific actor
            org_space_refreshed = (
                await session.execute(select(Spaces).where(Spaces.id == org_space.id))
            ).scalar_one()

            # Create actors for each user
            admin_actor = SpaceActor(
                space=_space_from_db(org_space_refreshed),
                user=admin_user,
            )
            editor_actor = SpaceActor(
                space=_space_from_db(org_space_refreshed),
                user=editor_user,
            )
            viewer_actor = SpaceActor(
                space=_space_from_db(org_space_refreshed),
                user=viewer_user,
            )

            # Verify permissions
            assert admin_actor.can_create_integrations() is True
            assert editor_actor.can_create_integrations() is False
            assert viewer_actor.can_create_integrations() is False

    @pytest.mark.skip(reason="Requires database fixtures - not a unit test")
    async def test_only_org_admin_can_delete_knowledge(
        self, db_container, tenant_factory, user_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify only ADMIN role can delete knowledge from org space."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create users with different roles
            admin_user = await user_factory(session, tenant_id=tenant.id)
            editor_user = await user_factory(session, tenant_id=tenant.id)
            viewer_user = await user_factory(session, tenant_id=tenant.id)

            # Create org space
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            # Assign roles
            admin_member = SpacesUsers(
                space_id=org_space.id,
                user_id=admin_user.id,
                role=SpaceRoleValue.ADMIN,
            )
            editor_member = SpacesUsers(
                space_id=org_space.id,
                user_id=editor_user.id,
                role=SpaceRoleValue.EDITOR,
            )
            viewer_member = SpacesUsers(
                space_id=org_space.id,
                user_id=viewer_user.id,
                role=SpaceRoleValue.VIEWER,
            )
            session.add(admin_member)
            session.add(editor_member)
            session.add(viewer_member)
            await session.flush()

            # Reload space for each user
            org_space_refreshed = (
                await session.execute(select(Spaces).where(Spaces.id == org_space.id))
            ).scalar_one()

            # Create actors for each user
            admin_actor = SpaceActor(
                space=_space_from_db(org_space_refreshed),
                user=admin_user,
            )
            editor_actor = SpaceActor(
                space=_space_from_db(org_space_refreshed),
                user=editor_user,
            )
            viewer_actor = SpaceActor(
                space=_space_from_db(org_space_refreshed),
                user=viewer_user,
            )

            # Verify delete permissions
            assert admin_actor.can_delete_integrations() is True
            assert editor_actor.can_delete_integrations() is False
            assert viewer_actor.can_delete_integrations() is False


class TestChildSpaceKnowledgePermissions:
    """Test permissions for distributed knowledge in child spaces."""

    @pytest.mark.skip(reason="Requires database fixtures - not a unit test")
    async def test_viewer_can_read_distributed_knowledge(
        self, db_container, tenant_factory, user_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify VIEWER role can read knowledge distributed to their space."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create users
            viewer_user = await user_factory(session, tenant_id=tenant.id)

            # Create org space
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            # Create child space
            child_space = Spaces(
                name="Child Space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=org_space.id,
            )
            session.add(child_space)
            await session.flush()

            # Add viewer to child space
            viewer_member = SpacesUsers(
                space_id=child_space.id,
                user_id=viewer_user.id,
                role=SpaceRoleValue.VIEWER,
            )
            session.add(viewer_member)
            await session.flush()

            # Reload space
            child_space_refreshed = (
                await session.execute(select(Spaces).where(Spaces.id == child_space.id))
            ).scalar_one()

            # Create actor
            viewer_actor = SpaceActor(
                space=_space_from_db(child_space_refreshed),
                user=viewer_user,
            )

            # VIEWER can read knowledge
            assert viewer_actor.can_read_integrations() is True

    async def test_viewer_cannot_delete_distributed_knowledge(
        self, db_container, tenant_factory, user_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify VIEWER role cannot delete distributed knowledge."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create users
            viewer_user = await user_factory(session, tenant_id=tenant.id)

            # Create org space
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            # Create child space
            child_space = Spaces(
                name="Child Space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=org_space.id,
            )
            session.add(child_space)
            await session.flush()

            # Add viewer to child space
            viewer_member = SpacesUsers(
                space_id=child_space.id,
                user_id=viewer_user.id,
                role=SpaceRoleValue.VIEWER,
            )
            session.add(viewer_member)
            await session.flush()

            # Reload space
            child_space_refreshed = (
                await session.execute(select(Spaces).where(Spaces.id == child_space.id))
            ).scalar_one()

            # Create actor
            viewer_actor = SpaceActor(
                space=_space_from_db(child_space_refreshed),
                user=viewer_user,
            )

            # VIEWER cannot delete
            assert viewer_actor.can_delete_integrations() is False

    @pytest.mark.skip(reason="Requires database fixtures - not a unit test")
    async def test_editor_can_delete_distributed_knowledge(
        self, db_container, tenant_factory, user_factory
    ):
        """Verify EDITOR role can delete distributed knowledge in child space."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create users
            editor_user = await user_factory(session, tenant_id=tenant.id)

            # Create org space
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            # Create child space
            child_space = Spaces(
                name="Child Space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=org_space.id,
            )
            session.add(child_space)
            await session.flush()

            # Add editor to child space
            editor_member = SpacesUsers(
                space_id=child_space.id,
                user_id=editor_user.id,
                role=SpaceRoleValue.EDITOR,
            )
            session.add(editor_member)
            await session.flush()

            # Reload space
            child_space_refreshed = (
                await session.execute(select(Spaces).where(Spaces.id == child_space.id))
            ).scalar_one()

            # Create actor
            editor_actor = SpaceActor(
                space=_space_from_db(child_space_refreshed),
                user=editor_user,
            )

            # EDITOR can delete
            assert editor_actor.can_delete_integrations() is True

    @pytest.mark.skip(reason="Requires database fixtures - not a unit test")
    async def test_admin_can_delete_distributed_knowledge(
        self, db_container, tenant_factory, user_factory
    ):
        """Verify ADMIN role can delete distributed knowledge in child space."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create users
            admin_user = await user_factory(session, tenant_id=tenant.id)

            # Create org space
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            # Create child space
            child_space = Spaces(
                name="Child Space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=org_space.id,
            )
            session.add(child_space)
            await session.flush()

            # Add admin to child space
            admin_member = SpacesUsers(
                space_id=child_space.id,
                user_id=admin_user.id,
                role=SpaceRoleValue.ADMIN,
            )
            session.add(admin_member)
            await session.flush()

            # Reload space
            child_space_refreshed = (
                await session.execute(select(Spaces).where(Spaces.id == child_space.id))
            ).scalar_one()

            # Create actor
            admin_actor = SpaceActor(
                space=_space_from_db(child_space_refreshed),
                user=admin_user,
            )

            # ADMIN can delete
            assert admin_actor.can_delete_integrations() is True
