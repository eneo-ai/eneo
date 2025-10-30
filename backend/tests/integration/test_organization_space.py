"""
Unit tests for Organization Space functionality.

Tests cover:
- Organization space creation
- Unique constraint enforcement
- Space hierarchy properties
- Race condition prevention
"""
import pytest
from sqlalchemy import select

from intric.database.tables.spaces_table import Spaces
from intric.spaces.space import Space


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


class TestOrganizationSpaceCreation:
    """Test organization space creation and constraints."""

    async def test_org_space_has_correct_properties(self, db_container, tenant_factory):
        """Verify org space has user_id=NULL, tenant_space_id=NULL."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create org space
            org_space = Spaces(
                name="Organization space",
                description="Shared knowledge for entire tenant",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            # Verify properties
            assert org_space.user_id is None
            assert org_space.tenant_space_id is None
            assert org_space.tenant_id == tenant.id
            assert org_space.name == "Organization space"

    async def test_is_organization_property(self, db_container, tenant_factory):
        """Verify Space.is_organization property works correctly."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create org space
            org_space_db = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space_db)
            await session.flush()

            # Create domain entity with minimal required fields
            org_space = _space_from_db(org_space_db)
            assert org_space.is_organization() is True

    async def test_child_space_is_not_organization(self, db_container, tenant_factory):
        """Verify child space is_organization() returns False."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create org space
            org_space_db = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space_db)
            await session.flush()

            # Create child space
            child_space_db = Spaces(
                name="Shared Space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=org_space_db.id,
            )
            session.add(child_space_db)
            await session.flush()

            # Create domain entity with minimal required fields
            child_space = _space_from_db(child_space_db)
            assert child_space.is_organization() is False
            assert child_space.tenant_space_id == org_space_db.id

    async def test_personal_space_is_not_organization(self, db_container, tenant_factory, user_factory):
        """Verify personal space is_organization() returns False."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)
            user = await user_factory(session, tenant_id=tenant.id)

            # Create org space
            org_space_db = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space_db)
            await session.flush()

            # Create personal space
            personal_space_db = Spaces(
                name="Personal",
                tenant_id=tenant.id,
                user_id=user.id,
                tenant_space_id=org_space_db.id,
            )
            session.add(personal_space_db)
            await session.flush()

            # Create domain entity with minimal required fields
            personal_space = _space_from_db(personal_space_db)
            assert personal_space.is_organization() is False
            assert personal_space.user_id == user.id

    async def test_unique_constraint_prevents_duplicate_org_spaces(self, db_container, tenant_factory):
        """Verify unique constraint prevents creating multiple org spaces per tenant."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create first org space
            org_space_1 = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space_1)
            await session.flush()

            # Try to create second org space for same tenant
            org_space_2 = Spaces(
                name="Organization space 2",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space_2)

            # Should raise unique constraint violation
            with pytest.raises(Exception):  # SQLAlchemy IntegrityError
                await session.flush()


class TestOrganizationSpaceHierarchy:
    """Test space hierarchy relationships."""

    async def test_child_spaces_reference_org_space(self, db_container, tenant_factory):
        """Verify child spaces correctly reference org space as parent."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create org space
            org_space_db = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space_db)
            await session.flush()

            # Create 3 child spaces
            child_spaces = []
            for i in range(3):
                child = Spaces(
                    name=f"Child Space {i}",
                    tenant_id=tenant.id,
                    user_id=None,
                    tenant_space_id=org_space_db.id,
                )
                session.add(child)
                child_spaces.append(child)
            await session.flush()

            # Verify all children reference org space
            for child in child_spaces:
                assert child.tenant_space_id == org_space_db.id
                assert child.tenant_id == tenant.id

    async def test_query_all_child_spaces_of_org_space(self, db_container, tenant_factory):
        """Verify query to find all child spaces of org space works correctly."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create org space
            org_space_db = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space_db)
            await session.flush()

            # Create 3 child spaces and 1 unrelated space
            for i in range(3):
                child = Spaces(
                    name=f"Child Space {i}",
                    tenant_id=tenant.id,
                    user_id=None,
                    tenant_space_id=org_space_db.id,
                )
                session.add(child)

            # Create space in different tenant (should not be included)
            other_tenant = await tenant_factory(session, name="Other Tenant")
            other_space = Spaces(
                name="Other Tenant Space",
                tenant_id=other_tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(other_space)
            await session.flush()

            # Query all child spaces
            stmt = select(Spaces).where(
                (Spaces.tenant_id == tenant.id)
                & (Spaces.tenant_space_id == org_space_db.id)
            )
            result = await session.execute(stmt)
            child_spaces = result.scalars().all()

            # Verify we get exactly 3 child spaces
            assert len(child_spaces) == 3
            for child in child_spaces:
                assert child.tenant_space_id == org_space_db.id

    async def test_multiple_organizations_in_same_instance(self, db_container, tenant_factory):
        """Verify multiple tenants can each have their own org space."""
        async with db_container() as container:
            session = container.session()

            # Create 3 tenants
            tenants = [await tenant_factory(session, name=f"Tenant {i}") for i in range(3)]

            # Create org space for each tenant
            org_spaces = []
            for tenant in tenants:
                org_space = Spaces(
                    name="Organization space",
                    tenant_id=tenant.id,
                    user_id=None,
                    tenant_space_id=None,
                )
                session.add(org_space)
                org_spaces.append(org_space)
            await session.flush()

            # Verify each tenant has exactly one org space
            for tenant, org_space in zip(tenants, org_spaces):
                stmt = select(Spaces).where(
                    (Spaces.tenant_id == tenant.id)
                    & (Spaces.user_id.is_(None))
                    & (Spaces.tenant_space_id.is_(None))
                )
                result = await session.execute(stmt)
                found_spaces = result.scalars().all()
                assert len(found_spaces) == 1
                assert found_spaces[0].id == org_space.id
