# Copyright (c) 2025 Sundsvalls Kommun
#
# Licensed under the MIT License.

from typing import Optional, Union
from uuid import UUID

from pydantic import BaseModel, Field

from eneo.main.models import NOT_PROVIDED, BaseResponse, ModelId, NotProvided
from eneo.security_classifications.domain.entities.security_classification import (
    SecurityClassification,
)


class SecurityClassificationCreatePublic(BaseModel):
    """Base model for security classification data."""

    name: str = Field(..., description="Name of the security classification")
    description: Optional[str] = Field(
        None, description="Description of the security classification"
    )
    set_lowest_security: bool = Field(
        True,
        description="Set lowest security level (0) if true, highest level if false",
    )


class SecurityClassificationUpdatePublic(BaseModel):
    id: UUID
    name: Union[str, NotProvided] = Field(
        NOT_PROVIDED, description="Name of the security classification"
    )
    description: Union[str, None, NotProvided] = Field(
        NOT_PROVIDED, description="Description of the security classification"
    )


class SecurityClassificationLevelsUpdateRequest(BaseModel):
    security_classifications: list[ModelId] = Field(
        ..., description="Security classification IDs"
    )


class SecurityClassificationSingleUpdate(BaseModel):
    """Model for updating an existing security classification's name and description only."""

    name: Union[str, NotProvided] = Field(
        NOT_PROVIDED, description="Name of the security classification"
    )
    description: Union[str, None, NotProvided] = Field(
        NOT_PROVIDED, description="Description of the security classification"
    )


class SecurityClassificationPublic(BaseResponse):
    """Basic security classification information."""

    name: str
    description: Optional[str]
    security_level: int

    @classmethod
    def from_domain(
        cls,
        security_classification: Optional[SecurityClassification] = None,
        return_none_if_not_enabled: bool = True,
    ):
        # Return None if classification is None or security is not enabled
        if return_none_if_not_enabled and (
            not security_classification or not security_classification.security_enabled
        ):
            return None

        if security_classification is None:
            return None

        return cls(
            created_at=security_classification.created_at,
            updated_at=security_classification.updated_at,
            id=security_classification.id,
            name=security_classification.name,
            description=security_classification.description,
            security_level=security_classification.security_level,
        )


class SecurityClassificationsListPublic(BaseModel):
    """All security classifications."""

    security_classifications: list[SecurityClassificationPublic]


class SecurityEnableRequest(BaseModel):
    """Request to enable or disable security classifications for a tenant."""

    enabled: bool = Field(
        ...,
        description="Whether security classifications should be enabled for the tenant",
    )


class SecurityEnableResponse(BaseModel):
    """Response after enabling or disabling security classifications for a tenant."""

    security_enabled: bool = Field(
        ...,
        description="Whether security classifications are now enabled for the tenant",
    )


class SecurityClassificationResponse(SecurityEnableResponse):
    security_enabled: bool
    security_classifications: list[SecurityClassificationPublic]
