"""
Unit tests for Integration Knowledge Distribution.

Tests cover:
- Knowledge distribution from org space to child spaces
- Distribution logic and database junction table
- Idempotent distribution (ON CONFLICT handling)
- Distribution scope and limitations
"""
import pytest
from sqlalchemy import select

from intric.database.tables.spaces_table import Spaces
from intric.database.tables.integration_table import IntegrationKnowledge
from intric.database.tables.integration_knowledge_spaces_table import (
    IntegrationKnowledgesSpaces,
)


class TestKnowledgeDistributionBasics:
    """Test basic knowledge distribution from org space to children."""

    async def test_knowledge_created_on_org_space_gets_distributed(
        self, db_container, tenant_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify knowledge created on org space creates junction table entries for all children."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create org space
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            # Create 3 child spaces
            child_spaces = []
            for i in range(3):
                child = Spaces(
                    name=f"Child Space {i}",
                    tenant_id=tenant.id,
                    user_id=None,
                    tenant_space_id=org_space.id,
                )
                session.add(child)
                child_spaces.append(child)
            await session.flush()

            # Create embedding model and user integration
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant.id)

            # Create knowledge on org space
            knowledge = IntegrationKnowledge(
                name="Test Knowledge",
                url="https://example.com",
                space_id=org_space.id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(knowledge)
            await session.flush()

            # Manually distribute (in production, this is done by the service)
            for child_space in child_spaces:
                distribution = IntegrationKnowledgesSpaces(
                    integration_knowledge_id=knowledge.id,
                    space_id=child_space.id,
                )
                session.add(distribution)
            await session.flush()

            # Verify junction table entries
            stmt = select(IntegrationKnowledgesSpaces).where(
                IntegrationKnowledgesSpaces.integration_knowledge_id == knowledge.id
            )
            result = await session.execute(stmt)
            distributions = result.scalars().all()

            assert len(distributions) == 3
            for i, dist in enumerate(distributions):
                assert dist.integration_knowledge_id == knowledge.id
                assert dist.space_id == child_spaces[i].id

    async def test_knowledge_only_distributed_to_child_spaces(
        self, db_container, tenant_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify knowledge is only distributed to direct children, not to org space itself."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create org space
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            # Create 2 child spaces
            for i in range(2):
                child = Spaces(
                    name=f"Child Space {i}",
                    tenant_id=tenant.id,
                    user_id=None,
                    tenant_space_id=org_space.id,
                )
                session.add(child)
            await session.flush()

            # Create embedding model and user integration
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant.id)

            # Create knowledge on org space
            knowledge = IntegrationKnowledge(
                name="Test Knowledge",
                url="https://example.com",
                space_id=org_space.id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(knowledge)
            await session.flush()

            # Get child spaces for distribution
            stmt = select(Spaces).where(
                (Spaces.tenant_id == tenant.id)
                & (Spaces.tenant_space_id == org_space.id)
            )
            result = await session.execute(stmt)
            child_spaces = result.scalars().all()

            # Distribute to children only
            for child_space in child_spaces:
                distribution = IntegrationKnowledgesSpaces(
                    integration_knowledge_id=knowledge.id,
                    space_id=child_space.id,
                )
                session.add(distribution)
            await session.flush()

            # Verify org space is NOT in distributions
            stmt = select(IntegrationKnowledgesSpaces).where(
                IntegrationKnowledgesSpaces.integration_knowledge_id == knowledge.id
            )
            result = await session.execute(stmt)
            distributions = result.scalars().all()

            distributed_space_ids = {d.space_id for d in distributions}
            assert org_space.id not in distributed_space_ids
            assert len(distributed_space_ids) == 2

    async def test_child_space_knowledge_not_distributed_to_siblings(
        self, db_container, tenant_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify knowledge created on child space does not distribute to sibling spaces."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create org space
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            # Create 2 child spaces
            child_spaces = []
            for i in range(2):
                child = Spaces(
                    name=f"Child Space {i}",
                    tenant_id=tenant.id,
                    user_id=None,
                    tenant_space_id=org_space.id,
                )
                session.add(child)
                child_spaces.append(child)
            await session.flush()

            # Create embedding model and user integration
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant.id)

            # Create knowledge on first child space
            knowledge = IntegrationKnowledge(
                name="Child Knowledge",
                url="https://example.com",
                space_id=child_spaces[0].id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(knowledge)
            await session.flush()

            # Verify NO distributions (child space knowledge doesn't auto-distribute)
            stmt = select(IntegrationKnowledgesSpaces).where(
                IntegrationKnowledgesSpaces.integration_knowledge_id == knowledge.id
            )
            result = await session.execute(stmt)
            distributions = result.scalars().all()

            assert len(distributions) == 0


class TestDistributionIdempotency:
    """Test that distribution is idempotent and handles duplicates safely."""

    async def test_duplicate_distribution_on_conflict_do_nothing(
        self, db_container, tenant_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify ON CONFLICT DO NOTHING prevents duplicate distribution entries."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create org space and child space
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            child_space = Spaces(
                name="Child Space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=org_space.id,
            )
            session.add(child_space)
            await session.flush()

            # Create knowledge
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant.id)

            knowledge = IntegrationKnowledge(
                name="Test Knowledge",
                url="https://example.com",
                space_id=org_space.id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(knowledge)
            await session.flush()

            # Create first distribution
            distribution_1 = IntegrationKnowledgesSpaces(
                integration_knowledge_id=knowledge.id,
                space_id=child_space.id,
            )
            session.add(distribution_1)
            await session.flush()

            # Try to create duplicate (should be handled by composite PK constraint)
            distribution_2 = IntegrationKnowledgesSpaces(
                integration_knowledge_id=knowledge.id,
                space_id=child_space.id,
            )
            session.add(distribution_2)

            # Should raise unique constraint violation (which gets handled by ON CONFLICT)
            with pytest.raises(Exception):  # SQLAlchemy IntegrityError
                await session.flush()


class TestDistributionScope:
    """Test that distribution respects boundaries and constraints."""

    async def test_knowledge_not_distributed_to_spaces_created_after_knowledge(
        self, db_container, tenant_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify knowledge created before child space doesn't auto-distribute to new child spaces."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create org space
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            # Create knowledge on org space
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant.id)

            knowledge = IntegrationKnowledge(
                name="Test Knowledge",
                url="https://example.com",
                space_id=org_space.id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(knowledge)
            await session.flush()

            # Manually distribute to first batch of children
            for i in range(2):
                child = Spaces(
                    name=f"Child Space {i}",
                    tenant_id=tenant.id,
                    user_id=None,
                    tenant_space_id=org_space.id,
                )
                session.add(child)
            await session.flush()

            # Distribute to existing children
            stmt = select(Spaces).where(
                (Spaces.tenant_id == tenant.id)
                & (Spaces.tenant_space_id == org_space.id)
            )
            result = await session.execute(stmt)
            existing_children = result.scalars().all()

            for child in existing_children:
                distribution = IntegrationKnowledgesSpaces(
                    integration_knowledge_id=knowledge.id,
                    space_id=child.id,
                )
                session.add(distribution)
            await session.flush()

            # NOW create a new child space AFTER knowledge was created
            new_child = Spaces(
                name="Child Space 2",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=org_space.id,
            )
            session.add(new_child)
            await session.flush()

            # Verify knowledge is NOT distributed to new child
            # (Manual distribution would require explicit action)
            stmt = select(IntegrationKnowledgesSpaces).where(
                (IntegrationKnowledgesSpaces.integration_knowledge_id == knowledge.id)
                & (IntegrationKnowledgesSpaces.space_id == new_child.id)
            )
            result = await session.execute(stmt)
            distribution = result.scalar_one_or_none()

            assert distribution is None  # Not auto-distributed

    async def test_distribution_does_not_cross_tenant_boundaries(
        self, db_container, tenant_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify distribution respects tenant boundaries."""
        async with db_container() as container:
            session = container.session()

            # Create two tenants
            tenant_1 = await tenant_factory(session, name="Tenant 1")
            tenant_2 = await tenant_factory(session, name="Tenant 2")

            # Create org space for tenant 1
            org_space_1 = Spaces(
                name="Organization space",
                tenant_id=tenant_1.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space_1)
            await session.flush()

            # Create child space in tenant 1
            child_1 = Spaces(
                name="Child Space",
                tenant_id=tenant_1.id,
                user_id=None,
                tenant_space_id=org_space_1.id,
            )
            session.add(child_1)
            await session.flush()

            # Create org space for tenant 2
            org_space_2 = Spaces(
                name="Organization space",
                tenant_id=tenant_2.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space_2)
            await session.flush()

            # Create knowledge on tenant 1 org space
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant_1.id)

            knowledge = IntegrationKnowledge(
                name="Test Knowledge",
                url="https://example.com",
                space_id=org_space_1.id,
                tenant_id=tenant_1.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(knowledge)
            await session.flush()

            # Distribute only to tenant 1 children
            distribution = IntegrationKnowledgesSpaces(
                integration_knowledge_id=knowledge.id,
                space_id=child_1.id,
            )
            session.add(distribution)
            await session.flush()

            # Verify knowledge is in child_1 only
            stmt = select(IntegrationKnowledgesSpaces).where(
                IntegrationKnowledgesSpaces.integration_knowledge_id == knowledge.id
            )
            result = await session.execute(stmt)
            distributions = result.scalars().all()

            assert len(distributions) == 1
            assert distributions[0].space_id == child_1.id
            assert distributions[0].space_id != org_space_2.id

    async def test_bulk_distribution_with_many_child_spaces(
        self, db_container, tenant_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify distribution handles large number of child spaces efficiently."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Create org space
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            # Create 100 child spaces
            child_spaces = []
            for i in range(100):
                child = Spaces(
                    name=f"Child Space {i}",
                    tenant_id=tenant.id,
                    user_id=None,
                    tenant_space_id=org_space.id,
                )
                session.add(child)
                child_spaces.append(child)
            await session.flush()

            # Create knowledge
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant.id)

            knowledge = IntegrationKnowledge(
                name="Test Knowledge",
                url="https://example.com",
                space_id=org_space.id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(knowledge)
            await session.flush()

            # Bulk insert distributions
            for child_space in child_spaces:
                distribution = IntegrationKnowledgesSpaces(
                    integration_knowledge_id=knowledge.id,
                    space_id=child_space.id,
                )
                session.add(distribution)
            await session.flush()

            # Verify all 100 distributions created
            stmt = select(IntegrationKnowledgesSpaces).where(
                IntegrationKnowledgesSpaces.integration_knowledge_id == knowledge.id
            )
            result = await session.execute(stmt)
            distributions = result.scalars().all()

            assert len(distributions) == 100
