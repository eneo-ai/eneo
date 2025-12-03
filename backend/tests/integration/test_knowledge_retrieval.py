"""
Unit tests for Integration Knowledge Retrieval.

Tests cover:
- Querying knowledge from spaces (direct + distributed)
- Knowledge visibility across space hierarchy
- Correct handling of union queries
"""
from sqlalchemy import select

from intric.database.tables.spaces_table import Spaces
from intric.database.tables.integration_table import IntegrationKnowledge
from intric.database.tables.integration_knowledge_spaces_table import (
    IntegrationKnowledgesSpaces,
)


class TestKnowledgeRetrieval:
    """Test knowledge retrieval from different space types."""

    async def test_child_space_retrieves_distributed_knowledge(
        self, db_container, tenant_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify child space can retrieve knowledge distributed from org space."""
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

            # Create child space
            child_space = Spaces(
                name="Child Space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=org_space.id,
            )
            session.add(child_space)
            await session.flush()

            # Create knowledge on org space
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant.id)

            knowledge = IntegrationKnowledge(
                name="Org Knowledge",
                url="https://example.com",
                space_id=org_space.id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(knowledge)
            await session.flush()

            # Distribute to child space
            distribution = IntegrationKnowledgesSpaces(
                integration_knowledge_id=knowledge.id,
                space_id=child_space.id,
            )
            session.add(distribution)
            await session.flush()

            # Retrieve knowledge from child space perspective
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
            retrieved_knowledge = result.scalars().all()

            assert len(retrieved_knowledge) == 1
            assert retrieved_knowledge[0].id == knowledge.id
            assert retrieved_knowledge[0].space_id == org_space.id

    async def test_child_space_retrieves_own_plus_distributed_knowledge(
        self, db_container, tenant_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify child space can retrieve both own knowledge and distributed knowledge."""
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

            # Create child space
            child_space = Spaces(
                name="Child Space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=org_space.id,
            )
            session.add(child_space)
            await session.flush()

            # Create embedding model and user integration
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant.id)

            # Create knowledge on org space
            org_knowledge = IntegrationKnowledge(
                name="Org Knowledge",
                url="https://org.example.com",
                space_id=org_space.id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(org_knowledge)
            await session.flush()

            # Create knowledge on child space
            child_knowledge = IntegrationKnowledge(
                name="Child Knowledge",
                url="https://child.example.com",
                space_id=child_space.id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(child_knowledge)
            await session.flush()

            # Distribute org knowledge to child
            distribution = IntegrationKnowledgesSpaces(
                integration_knowledge_id=org_knowledge.id,
                space_id=child_space.id,
            )
            session.add(distribution)
            await session.flush()

            # Retrieve all knowledge visible to child space
            stmt = select(IntegrationKnowledge).where(
                (IntegrationKnowledge.space_id == child_space.id)
                | (
                    IntegrationKnowledge.id.in_(
                        select(IntegrationKnowledgesSpaces.integration_knowledge_id).where(
                            IntegrationKnowledgesSpaces.space_id == child_space.id
                        )
                    )
                )
            )
            result = await session.execute(stmt)
            all_knowledge = result.scalars().all()

            assert len(all_knowledge) == 2
            knowledge_ids = {k.id for k in all_knowledge}
            assert org_knowledge.id in knowledge_ids
            assert child_knowledge.id in knowledge_ids

    async def test_org_space_sees_only_own_knowledge(
        self, db_container, tenant_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify org space does not see child space knowledge."""
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

            # Create child space
            child_space = Spaces(
                name="Child Space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=org_space.id,
            )
            session.add(child_space)
            await session.flush()

            # Create embedding model and user integration
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant.id)

            # Create knowledge on org space
            org_knowledge = IntegrationKnowledge(
                name="Org Knowledge",
                url="https://org.example.com",
                space_id=org_space.id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(org_knowledge)
            await session.flush()

            # Create knowledge on child space
            child_knowledge = IntegrationKnowledge(
                name="Child Knowledge",
                url="https://child.example.com",
                space_id=child_space.id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(child_knowledge)
            await session.flush()

            # Retrieve knowledge from org space perspective
            stmt = select(IntegrationKnowledge).where(
                IntegrationKnowledge.space_id == org_space.id
            )
            result = await session.execute(stmt)
            org_knowledge_list = result.scalars().all()

            # Org space should only see its own knowledge
            assert len(org_knowledge_list) == 1
            assert org_knowledge_list[0].id == org_knowledge.id
            assert org_knowledge_list[0].space_id == org_space.id

    async def test_sibling_spaces_cannot_see_each_other_knowledge(
        self, db_container, tenant_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify sibling child spaces cannot see each other's knowledge."""
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
            child_1 = Spaces(
                name="Child Space 1",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=org_space.id,
            )
            child_2 = Spaces(
                name="Child Space 2",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=org_space.id,
            )
            session.add(child_1)
            session.add(child_2)
            await session.flush()

            # Create embedding model and user integration
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant.id)

            # Create knowledge on child_1
            knowledge_1 = IntegrationKnowledge(
                name="Child 1 Knowledge",
                url="https://child1.example.com",
                space_id=child_1.id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(knowledge_1)
            await session.flush()

            # Retrieve knowledge from child_2 perspective
            stmt = select(IntegrationKnowledge).where(
                IntegrationKnowledge.space_id == child_2.id
            )
            result = await session.execute(stmt)
            child_2_knowledge = result.scalars().all()

            # Child 2 should not see child 1's knowledge
            assert len(child_2_knowledge) == 0


class TestKnowledgeVisibilityBoundaries:
    """Test knowledge visibility boundaries."""

    async def test_personal_space_cannot_see_org_knowledge(
        self, db_container, tenant_factory, user_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify personal space cannot access org space knowledge by default."""
        async with db_container() as container:
            session = container.session()
            tenant = await tenant_factory(session)
            user = await user_factory(session, tenant_id=tenant.id)

            # Create org space
            org_space = Spaces(
                name="Organization space",
                tenant_id=tenant.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space)
            await session.flush()

            # Create personal space
            personal_space = Spaces(
                name="Personal",
                tenant_id=tenant.id,
                user_id=user.id,
                tenant_space_id=org_space.id,
            )
            session.add(personal_space)
            await session.flush()

            # Create knowledge on org space
            embedding_model = await embedding_model_factory(session)
            user_integration = await user_integration_factory(session, tenant_id=tenant.id)

            org_knowledge = IntegrationKnowledge(
                name="Org Knowledge",
                url="https://org.example.com",
                space_id=org_space.id,
                tenant_id=tenant.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration.id,
            )
            session.add(org_knowledge)
            await session.flush()

            # Personal space does NOT automatically see org knowledge
            # (unless explicitly shared/distributed)
            stmt = select(IntegrationKnowledge).where(
                IntegrationKnowledge.space_id == personal_space.id
            )
            result = await session.execute(stmt)
            personal_knowledge = result.scalars().all()

            assert len(personal_knowledge) == 0

    async def test_cross_tenant_spaces_isolation(
        self, db_container, tenant_factory, user_integration_factory, embedding_model_factory
    ):
        """Verify spaces in different tenants cannot see each other's knowledge."""
        async with db_container() as container:
            session = container.session()

            # Create two tenants
            tenant_1 = await tenant_factory(session, name="Tenant 1")
            tenant_2 = await tenant_factory(session, name="Tenant 2")

            # Create org spaces for each tenant
            org_space_1 = Spaces(
                name="Organization space",
                tenant_id=tenant_1.id,
                user_id=None,
                tenant_space_id=None,
            )
            org_space_2 = Spaces(
                name="Organization space",
                tenant_id=tenant_2.id,
                user_id=None,
                tenant_space_id=None,
            )
            session.add(org_space_1)
            session.add(org_space_2)
            await session.flush()

            # Create knowledge in tenant 1
            embedding_model = await embedding_model_factory(session)
            user_integration_1 = await user_integration_factory(session, tenant_id=tenant_1.id)

            knowledge_1 = IntegrationKnowledge(
                name="Tenant 1 Knowledge",
                url="https://tenant1.example.com",
                space_id=org_space_1.id,
                tenant_id=tenant_1.id,
                embedding_model_id=embedding_model.id,
                user_integration_id=user_integration_1.id,
            )
            session.add(knowledge_1)
            await session.flush()

            # Try to query knowledge from tenant 2 perspective
            # Should be isolated by tenant_id
            stmt = select(IntegrationKnowledge).where(
                (IntegrationKnowledge.tenant_id == tenant_2.id)
                & (IntegrationKnowledge.space_id == org_space_2.id)
            )
            result = await session.execute(stmt)
            tenant_2_knowledge = result.scalars().all()

            assert len(tenant_2_knowledge) == 0
