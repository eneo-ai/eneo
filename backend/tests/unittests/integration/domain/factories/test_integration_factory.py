import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from eneo.integration.domain.entities.integration import Integration
from eneo.integration.domain.factories.integration_factory import IntegrationFactory


class TestIntegrationFactory(unittest.TestCase):
    def test_create_entity(self):
        # Arrange
        integration_id = uuid4()
        db_record = MagicMock()
        db_record.id = integration_id
        db_record.name = "Test Integration"
        db_record.description = "Test Description"
        db_record.integration_type = "confluence"

        # Act
        integration = IntegrationFactory.create_entity(db_record)

        # Assert
        self.assertIsInstance(integration, Integration)
        self.assertEqual(integration.id, integration_id)
        self.assertEqual(integration.name, "Test Integration")
        self.assertEqual(integration.description, "Test Description")
        self.assertEqual(integration.integration_type, "confluence")

    def test_create_entities(self):
        # Arrange
        num_records = 3
        db_records = []

        for i in range(num_records):
            record = MagicMock()
            record.id = uuid4()
            record.name = f"Test Integration {i}"
            record.description = f"Test Description {i}"
            record.integration_type = "confluence" if i % 2 == 0 else "sharepoint"
            db_records.append(record)

        # Act
        integrations = IntegrationFactory.create_entities(db_records)

        # Assert
        self.assertEqual(len(integrations), num_records)

        for i, integration in enumerate(integrations):
            self.assertIsInstance(integration, Integration)
            self.assertEqual(integration.id, db_records[i].id)
            self.assertEqual(integration.name, db_records[i].name)
            self.assertEqual(integration.description, db_records[i].description)
            self.assertEqual(
                integration.integration_type, db_records[i].integration_type
            )


if __name__ == "__main__":
    unittest.main()
