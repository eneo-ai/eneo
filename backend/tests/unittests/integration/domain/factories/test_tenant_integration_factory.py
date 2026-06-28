import unittest
from unittest.mock import MagicMock
from uuid import uuid4

from eneo.integration.domain.entities.tenant_integration import TenantIntegration
from eneo.integration.domain.factories.tenant_integration_factory import (
    TenantIntegrationFactory,
)


class TestTenantIntegrationFactory(unittest.TestCase):
    def setUp(self):
        self.integration_mock = MagicMock()
        self.integration_mock.id = uuid4()
        self.integration_mock.name = "Test Integration"
        self.integration_mock.description = "Test Description"
        self.integration_mock.integration_type = "confluence"

    def test_create_entity(self):
        # Arrange
        tenant_id = uuid4()
        integration_id = uuid4()
        db_record = MagicMock()
        db_record.id = integration_id
        db_record.tenant_id = tenant_id
        db_record.integration = self.integration_mock

        # Act
        tenant_integration = TenantIntegrationFactory.create_entity(db_record)

        # Assert
        self.assertIsInstance(tenant_integration, TenantIntegration)
        self.assertEqual(tenant_integration.id, integration_id)
        self.assertEqual(tenant_integration.tenant_id, tenant_id)
        self.assertEqual(tenant_integration.integration.id, self.integration_mock.id)
        self.assertEqual(
            tenant_integration.integration.name, self.integration_mock.name
        )
        self.assertEqual(
            tenant_integration.integration.description,
            self.integration_mock.description,
        )
        self.assertEqual(
            tenant_integration.integration.integration_type,
            self.integration_mock.integration_type,
        )

    def test_create_entities(self):
        # Arrange
        num_records = 3
        db_records = []

        for i in range(num_records):
            record = MagicMock()
            record.id = uuid4()
            record.tenant_id = uuid4()
            record.integration = self.integration_mock
            db_records.append(record)

        # Act
        tenant_integrations = TenantIntegrationFactory.create_entities(db_records)

        # Assert
        self.assertEqual(len(tenant_integrations), num_records)

        for i, tenant_integration in enumerate(tenant_integrations):
            self.assertIsInstance(tenant_integration, TenantIntegration)
            self.assertEqual(tenant_integration.id, db_records[i].id)
            self.assertEqual(tenant_integration.tenant_id, db_records[i].tenant_id)
            self.assertEqual(
                tenant_integration.integration.id, self.integration_mock.id
            )
            self.assertEqual(
                tenant_integration.integration.name, self.integration_mock.name
            )
            self.assertEqual(
                tenant_integration.integration.description,
                self.integration_mock.description,
            )
            self.assertEqual(
                tenant_integration.integration.integration_type,
                self.integration_mock.integration_type,
            )


if __name__ == "__main__":
    unittest.main()
