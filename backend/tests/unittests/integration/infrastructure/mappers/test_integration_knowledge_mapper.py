import unittest
from unittest.mock import MagicMock, patch
from uuid import uuid4

from intric.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from intric.integration.infrastructure.mappers.integration_knowledge_mapper import (
    IntegrationKnowledgeMapper,
)


class TestIntegrationKnowledgeMapper(unittest.TestCase):
    def setUp(self):
        """Set up test fixtures."""
        self.mapper = IntegrationKnowledgeMapper()

        # Sample integration knowledge data
        self.knowledge_id = uuid4()
        self.name = "Test Knowledge"
        self.url = "https://example.com/knowledge"
        self.tenant_id = uuid4()
        self.space_id = uuid4()
        self.size = 1024

        # Create mock dependencies
        self.user_integration_mock = MagicMock()
        self.user_integration_mock.id = uuid4()

        self.embedding_model_mock = MagicMock()
        self.embedding_model_mock.id = uuid4()

    def test_to_db_dict(self):
        """Test mapping from domain entity to DB dictionary."""
        # Create a domain entity
        knowledge = IntegrationKnowledge(
            id=self.knowledge_id,
            name=self.name,
            url=self.url,
            tenant_id=self.tenant_id,
            space_id=self.space_id,
            user_integration=self.user_integration_mock,
            embedding_model=self.embedding_model_mock,
            size=self.size,
        )

        # Map to DB dictionary
        db_dict = self.mapper.to_db_dict(knowledge)

        # Assertions
        self.assertEqual(db_dict["name"], self.name)
        self.assertEqual(db_dict["url"], self.url)
        self.assertEqual(db_dict["tenant_id"], self.tenant_id)
        self.assertEqual(db_dict["space_id"], self.space_id)
        self.assertEqual(db_dict["user_integration_id"], self.user_integration_mock.id)
        self.assertEqual(db_dict["embedding_model_id"], self.embedding_model_mock.id)
        self.assertEqual(db_dict["size"], self.size)

        # Ensure ID is not in the dictionary (as it should be handled by SQLAlchemy)
        self.assertNotIn("id", db_dict)

    def test_to_db_dict_includes_resource_type_and_drive_id(self):
        """Test that resource_type and drive_id are included in DB dictionary."""
        # Create a domain entity with OneDrive fields
        knowledge = IntegrationKnowledge(
            id=self.knowledge_id,
            name=self.name,
            url=self.url,
            tenant_id=self.tenant_id,
            space_id=self.space_id,
            user_integration=self.user_integration_mock,
            embedding_model=self.embedding_model_mock,
            size=self.size,
            resource_type="onedrive",
            drive_id="drive-123-abc",
        )

        # Map to DB dictionary
        db_dict = self.mapper.to_db_dict(knowledge)

        # Assert resource_type and drive_id are included
        self.assertEqual(db_dict["resource_type"], "onedrive")
        self.assertEqual(db_dict["drive_id"], "drive-123-abc")

    def test_to_db_dict_includes_original_name(self):
        """Test that original_name is included in DB dictionary."""
        # Create a domain entity with original_name
        knowledge = IntegrationKnowledge(
            id=self.knowledge_id,
            name="Renamed Knowledge",
            original_name="Original SharePoint Name",
            url=self.url,
            tenant_id=self.tenant_id,
            space_id=self.space_id,
            user_integration=self.user_integration_mock,
            embedding_model=self.embedding_model_mock,
            size=self.size,
        )

        # Map to DB dictionary
        db_dict = self.mapper.to_db_dict(knowledge)

        # Assert original_name is included
        self.assertEqual(db_dict["name"], "Renamed Knowledge")
        self.assertEqual(db_dict["original_name"], "Original SharePoint Name")

    @patch(
        "intric.integration.domain.factories.integration_knowledge_factory.IntegrationKnowledgeFactory.create_entity"  # noqa
    )
    def test_to_entity(self, mock_create_entity):
        """Test mapping from DB model to domain entity using factory."""
        # Create a mock DB model
        db_model = MagicMock()
        db_model.id = self.knowledge_id
        db_model.name = self.name
        db_model.url = self.url
        db_model.tenant_id = self.tenant_id
        db_model.space_id = self.space_id
        db_model.user_integration = self.user_integration_mock
        db_model.embedding_model = self.embedding_model_mock
        db_model.size = self.size

        # Create a mock entity to be returned by the factory
        mock_entity = IntegrationKnowledge(
            id=self.knowledge_id,
            name=self.name,
            url=self.url,
            tenant_id=self.tenant_id,
            space_id=self.space_id,
            user_integration=self.user_integration_mock,
            embedding_model=self.embedding_model_mock,
            size=self.size,
        )
        mock_create_entity.return_value = mock_entity

        # Map to entity
        entity = self.mapper.to_entity(db_model, embedding_model=self.embedding_model_mock)

        # Assert factory was called with db_model
        mock_create_entity.assert_called_once_with(
            record=db_model, embedding_model=self.embedding_model_mock
        )

        # Assert returned entity is what we expect
        self.assertEqual(entity, mock_entity)

    @patch(
        "intric.integration.domain.factories.integration_knowledge_factory.IntegrationKnowledgeFactory.create_entities"  # noqa
    )
    def test_to_entities(self, mock_create_entities):
        """Test mapping from DB models to domain entities using factory."""
        # Create mock DB models
        db_models = [MagicMock() for _ in range(3)]

        # Create mock entities to be returned by the factory
        mock_entities = [
            IntegrationKnowledge(
                id=uuid4(),
                name=f"Test Knowledge {i}",
                url=f"https://example.com/knowledge/{i}",
                tenant_id=self.tenant_id,
                space_id=self.space_id,
                user_integration=self.user_integration_mock,
                embedding_model=self.embedding_model_mock,
                size=i * 1000,
            )
            for i in range(3)
        ]
        mock_create_entities.return_value = mock_entities

        # Map to entities
        entities = self.mapper.to_entities(db_models, embedding_models=[self.embedding_model_mock])

        # Assert factory was called with db_models
        mock_create_entities.assert_called_once_with(
            records=db_models, embedding_models=[self.embedding_model_mock]
        )

        # Assert returned entities are what we expect
        self.assertEqual(entities, mock_entities)


if __name__ == "__main__":
    unittest.main()
