# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from datetime import datetime
from typing import Optional, Union
from uuid import UUID

from intric.base.base_entity import Entity
from intric.database.tables.security_classifications_table import (
    SecurityClassification as SecurityDBModel,
)
from intric.main.models import NOT_PROVIDED, NotProvided, is_provided


class SecurityClassification(Entity):
    """Domain model for security classifications."""

    def __init__(
        self,
        tenant_id: UUID,
        name: str,
        description: Optional[str] = None,
        security_level: int = 0,
        id: Optional[UUID] = None,
        created_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        security_enabled: bool = False,
    ):
        super().__init__(id=id, created_at=created_at, updated_at=updated_at)
        self.tenant_id = tenant_id
        self.name = name
        self.description = description
        self.security_level = security_level
        self.security_enabled = security_enabled

    @classmethod
    def create(
        cls,
        tenant_id: UUID,
        name: str,
        description: Optional[str] = None,
    ) -> "SecurityClassification":
        return cls(
            tenant_id=tenant_id,
            name=name,
            description=description,
            security_level=0,
            id=None,
            created_at=None,
            updated_at=None,
        )

    @classmethod
    def to_domain(
        cls, db_security_classification: Optional[SecurityDBModel] = None
    ) -> "SecurityClassification | None":
        if db_security_classification is None:
            return None

        # Get security_enabled from tenant if available, default to False
        security_enabled = False
        if db_security_classification.tenant is not None:
            security_enabled = db_security_classification.tenant.security_enabled

        return cls(
            id=db_security_classification.id,
            tenant_id=db_security_classification.tenant_id,
            name=db_security_classification.name,
            description=db_security_classification.description,
            security_level=db_security_classification.security_level,
            created_at=db_security_classification.created_at,
            updated_at=db_security_classification.updated_at,
            security_enabled=security_enabled,
        )

    def update(
        self,
        name: Union[str, NotProvided] = NOT_PROVIDED,
        description: Union[str, None, NotProvided] = NOT_PROVIDED,
        security_level: Optional[int] = None,
    ) -> "SecurityClassification":
        """Update the security classification properties.

        Args:
            name: New name for the security classification
            description: New description for the security classification
            security_level: New security level value

        Returns:
            The updated security classification
        """
        if is_provided(name):
            self.name = name
        if is_provided(description):
            self.description = description
        if security_level is not None:
            self.security_level = security_level

        return self

    def is_greater_than(
        self,
        security_classification: Optional["SecurityClassification"],
    ) -> bool:
        if self.security_enabled:
            if security_classification is None:
                return True
            else:
                return self.security_level > security_classification.security_level

        return False
