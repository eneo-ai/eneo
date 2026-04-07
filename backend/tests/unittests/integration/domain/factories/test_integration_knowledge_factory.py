import unittest
from datetime import datetime
from unittest.mock import MagicMock
from uuid import uuid4

from intric.integration.domain.entities.integration_knowledge import (
    IntegrationKnowledge,
)
from intric.integration.domain.factories.integration_knowledge_factory import (
    IntegrationKnowledgeFactory,
)


class TestIntegrationKnowledgeFactory(unittest.TestCase):
    def setUp(self):
        # Create mock user integration and embedding model
        self.user_integration_mock = MagicMock()
        self.user_integration_mock.id = uuid4()

        self.embedding_model_mock = MagicMock()
        self.embedding_model_mock.id = uuid4()
        self.embedding_model_mock.name = "Test Embedding Model"

    def test_create_entity(self):
        # Arrange
        integration_id = uuid4()
        tenant_id = uuid4()
        space_id = uuid4()
        created_at = datetime.now()
        updated_at = datetime.now()

        db_record = MagicMock()
        db_record.id = integration_id
        db_record.name = "Test Knowledge Base"
        db_record.url = "https://example.com/kb"
        db_record.tenant_id = tenant_id
        db_record.space_id = space_id
        db_record.user_integration = self.user_integration_mock
        db_record.embedding_model = self.embedding_model_mock
        db_record.created_at = created_at
        db_record.updated_at = updated_at
        db_record.size = 1024

        # Act
        knowledge = IntegrationKnowledgeFactory.create_entity(
            db_record, embedding_model=self.embedding_model_mock
        )

        # Assert
        self.assertIsInstance(knowledge, IntegrationKnowledge)
        self.assertEqual(knowledge.id, integration_id)
        self.assertEqual(knowledge.name, "Test Knowledge Base")
        self.assertEqual(knowledge.url, "https://example.com/kb")
        self.assertEqual(knowledge.tenant_id, tenant_id)
        self.assertEqual(knowledge.space_id, space_id)
        self.assertEqual(knowledge.user_integration, self.user_integration_mock)
        self.assertEqual(knowledge.embedding_model, self.embedding_model_mock)
        self.assertEqual(knowledge.created_at, created_at)
        self.assertEqual(knowledge.updated_at, updated_at)
        self.assertEqual(knowledge.size, 1024)

    def test_create_entity_with_default_size(self):
        # Arrange
        db_record = MagicMock()
        db_record.id = uuid4()
        db_record.name = "Test Knowledge Base"
        db_record.url = "https://example.com/kb"
        db_record.tenant_id = uuid4()
        db_record.space_id = uuid4()
        db_record.user_integration = self.user_integration_mock
        db_record.embedding_model = self.embedding_model_mock
        db_record.created_at = datetime.now()
        db_record.updated_at = datetime.now()
        db_record.size = None

        # Act
        knowledge = IntegrationKnowledgeFactory.create_entity(
            db_record, embedding_model=self.embedding_model_mock
        )

        # Assert
        self.assertEqual(knowledge.size, 0)  # Default size is 0

    def test_create_entities(self):
        # Arrange
        num_records = 3
        db_records = []

        for i in range(num_records):
            record = MagicMock()
            record.id = uuid4()
            record.name = f"Test Knowledge Base {i}"
            record.url = f"https://example.com/kb/{i}"
            record.tenant_id = uuid4()
            record.space_id = uuid4()
            record.user_integration = self.user_integration_mock
            record.embedding_model = self.embedding_model_mock
            record.embedding_model_id = self.embedding_model_mock.id
            record.created_at = datetime.now()
            record.updated_at = datetime.now()
            record.size = i * 1000
            db_records.append(record)

        # Act
        knowledge_list = IntegrationKnowledgeFactory.create_entities(
            db_records,
            embedding_models=[self.embedding_model_mock for _ in range(num_records)],
        )

        # Assert
        self.assertEqual(len(knowledge_list), num_records)

        for i, knowledge in enumerate(knowledge_list):
            self.assertIsInstance(knowledge, IntegrationKnowledge)
            self.assertEqual(knowledge.id, db_records[i].id)
            self.assertEqual(knowledge.name, db_records[i].name)
            self.assertEqual(knowledge.url, db_records[i].url)
            self.assertEqual(knowledge.tenant_id, db_records[i].tenant_id)
            self.assertEqual(knowledge.space_id, db_records[i].space_id)
            self.assertEqual(knowledge.user_integration, self.user_integration_mock)
            self.assertEqual(knowledge.embedding_model, self.embedding_model_mock)
            self.assertEqual(knowledge.created_at, db_records[i].created_at)
            self.assertEqual(knowledge.updated_at, db_records[i].updated_at)
            self.assertEqual(knowledge.size, db_records[i].size)


if __name__ == "__main__":
    unittest.main()
