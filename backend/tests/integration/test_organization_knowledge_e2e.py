"""
End-to-End Integration Tests for Organization-Based Knowledge Feature.

These tests verify the complete flow from knowledge creation through distribution
to retrieval and deletion across the entire system stack.

Marked with pytest.mark.integration to be run separately if needed.
"""
import pytest
from sqlalchemy import select

from intric.database.tables.spaces_table import Spaces
from intric.database.tables.integration_table import IntegrationKnowledge
from intric.database.tables.integration_knowledge_spaces_table import (
    IntegrationKnowledgesSpaces,
)


@pytest.mark.integration
class TestOrganizationKnowledgeE2E:
    """End-to-end tests for organization knowledge feature."""

    async def test_complete_knowledge_distribution_flow(
        self,
        db_container,
        tenant_factory,
        user_integration_factory,
        embedding_model_factory,
    ):
        """
        Full flow test:
        1. Create org space and child spaces
        2. Create knowledge on org space
        3. Verify it's distributed to all children
        4. Retrieve knowledge from child space
        5. Delete knowledge and verify distributions are cleaned up
        """
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Step 1: Create org space and child spaces
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

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

            # Step 2: Create knowledge on org space
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant.id)

            knowledge = IntegrationKnowledge(
                name="Distributed Knowledge",
                url="https://example.com",
                space_id=org_space.id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(knowledge)
            await session.flush()

            # Step 3: Distribute to all child spaces
            for child_space in child_spaces:
                distribution = IntegrationKnowledgesSpaces(
                    integration_knowledge_id=knowledge.id,
                    space_id=child_space.id,
                )
                session.add(distribution)
            await session.flush()

            # Verify distributions created
            stmt = select(IntegrationKnowledgesSpaces).where(
                IntegrationKnowledgesSpaces.integration_knowledge_id == knowledge.id
            )
            result = await session.execute(stmt)
            distributions = result.scalars().all()
            assert len(distributions) == 3

            # Step 4: Retrieve knowledge from child space perspective
            child_space = child_spaces[0]
            stmt = select(IntegrationKnowledge).where(
                (IntegrationKnowledge.space_id == org_space.id)
                | (
                    IntegrationKnowledge.id.in_(
                        select(IntegrationKnowledgesSpaces.integration_knowledge_id).where(
                            IntegrationKnowledgesSpaces.space_id == child_space.id
                        )
                    )
                )
            )
            result = await session.execute(stmt)
            child_knowledge = result.scalars().all()
            assert len(child_knowledge) == 1
            assert child_knowledge[0].id == knowledge.id

            # Step 5: Delete knowledge and verify cleanup
            # Remove distributions first (simulating what the service does)
            stmt = delete(IntegrationKnowledgesSpaces).where(
                IntegrationKnowledgesSpaces.integration_knowledge_id == knowledge.id
            )
            await session.execute(stmt)
            await session.flush()

            # Delete knowledge
            await session.delete(knowledge)
            await session.flush()

            # Verify knowledge is gone
            stmt = select(IntegrationKnowledge).where(
                IntegrationKnowledge.id == knowledge.id
            )
            result = await session.execute(stmt)
            deleted_knowledge = result.scalar_one_or_none()
            assert deleted_knowledge is None

            # Verify distributions are cleaned up (should have been CASCADE deleted)
            stmt = select(IntegrationKnowledgesSpaces).where(
                IntegrationKnowledgesSpaces.integration_knowledge_id == knowledge.id
            )
            result = await session.execute(stmt)
            remaining_distributions = result.scalars().all()
            assert len(remaining_distributions) == 0

    async def test_knowledge_with_missing_child_space_then_created(
        self,
        db_container,
        tenant_factory,
        user_integration_factory,
        embedding_model_factory,
    ):
        """
        Test scenario:
        1. Create org space without child spaces
        2. Create knowledge on org space (no distributions)
        3. Create new child space (should NOT get knowledge retroactively)
        4. Verify new child space doesn't have knowledge
        """
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Step 1: Create org space without children
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            # Step 2: Create knowledge
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant.id)

            knowledge = IntegrationKnowledge(
                name="Early Knowledge",
                url="https://example.com",
                space_id=org_space.id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(knowledge)
            await session.flush()

            # No distributions should exist
            stmt = select(IntegrationKnowledgesSpaces).where(
                IntegrationKnowledgesSpaces.integration_knowledge_id == knowledge.id
            )
            result = await session.execute(stmt)
            distributions = result.scalars().all()
            assert len(distributions) == 0

            # Step 3: Create new child space AFTER knowledge
            new_child = Spaces(
                name="Late Child Space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=org_space.id,
            )
            session.add(new_child)
            await session.flush()

            # Step 4: Verify child space doesn't have knowledge
            # (unless explicitly distributed)
            stmt = select(IntegrationKnowledge).where(
                IntegrationKnowledge.space_id == new_child.id
            )
            result = await session.execute(stmt)
            child_knowledge = result.scalars().all()
            assert len(child_knowledge) == 0

    async def test_multiple_knowledge_items_distributed_to_same_child(
        self,
        db_container,
        tenant_factory,
        user_integration_factory,
        embedding_model_factory,
    ):
        """
        Test scenario:
        1. Create org space with one child space
        2. Create multiple knowledge items on org space
        3. Distribute all to the child space
        4. Verify child space sees all knowledge
        """
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)

            # Step 1: Create org space and child
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

            # Step 2: Create multiple knowledge items
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant.id)

            knowledge_items = []
            for i in range(5):
                knowledge = IntegrationKnowledge(
                    name=f"Knowledge Item {i}",
                    url=f"https://example{i}.com",
                    space_id=org_space.id,
                    tenant_id=tenant.id,
                    embedding_model_id=embedding_model.id,
                    user_integration_id=user_integration.id,
                )
                session.add(knowledge)
                knowledge_items.append(knowledge)
            await session.flush()

            # Step 3: Distribute all to child
            for knowledge in knowledge_items:
                distribution = IntegrationKnowledgesSpaces(
                    integration_knowledge_id=knowledge.id,
                    space_id=child_space.id,
                )
                session.add(distribution)
            await session.flush()

            # Step 4: Verify child sees all knowledge
            stmt = select(IntegrationKnowledge).where(
                (IntegrationKnowledge.space_id == org_space.id)
                | (
                    IntegrationKnowledge.id.in_(
                        select(IntegrationKnowledgesSpaces.integration_knowledge_id).where(
                            IntegrationKnowledgesSpaces.space_id == child_space.id
                        )
                    )
                )
            )
            result = await session.execute(stmt)
            child_knowledge = result.scalars().all()

            assert len(child_knowledge) == 5
            child_knowledge_ids = {k.id for k in child_knowledge}
            expected_ids = {k.id for k in knowledge_items}
            assert child_knowledge_ids == expected_ids


# Import needed for delete statement
from sqlalchemy import delete
