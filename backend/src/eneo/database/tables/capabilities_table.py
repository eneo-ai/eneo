"""Capability intent belongs to its owner, independently of provider lifetime."""

from uuid import UUID

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from eneo.database.tables.base_class import BaseCrossReference
from eneo.mcp_servers.domain.capabilities import CapabilityPurpose


class SpaceCapabilities(BaseCrossReference):
    def __init__(
        self, *, purpose: CapabilityPurpose, space_id: UUID | None = None
    ) -> None:
        self.purpose = purpose
        if space_id is not None:
            self.space_id = space_id

    space_id: Mapped[UUID] = mapped_column(
        ForeignKey("spaces.id", ondelete="CASCADE"), primary_key=True
    )
    purpose: Mapped[CapabilityPurpose] = mapped_column(String(), primary_key=True)
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('web_search', 'image_generation')",
            name="ck_space_capability_purpose",
        ),
    )


class AssistantCapabilities(BaseCrossReference):
    def __init__(
        self, *, purpose: CapabilityPurpose, assistant_id: UUID | None = None
    ) -> None:
        self.purpose = purpose
        if assistant_id is not None:
            self.assistant_id = assistant_id

    assistant_id: Mapped[UUID] = mapped_column(
        ForeignKey("assistants.id", ondelete="CASCADE"), primary_key=True
    )
    purpose: Mapped[CapabilityPurpose] = mapped_column(String(), primary_key=True)
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('web_search', 'image_generation')",
            name="ck_assistant_capability_purpose",
        ),
    )


class GovernancePolicyCapabilities(BaseCrossReference):
    def __init__(
        self,
        *,
        purpose: CapabilityPurpose,
        policy_id: UUID | None = None,
        is_default_enabled: bool = True,
    ) -> None:
        self.purpose = purpose
        if policy_id is not None:
            self.policy_id = policy_id
        self.is_default_enabled = is_default_enabled

    policy_id: Mapped[UUID] = mapped_column(
        ForeignKey("governance_policies.id", ondelete="CASCADE"), primary_key=True
    )
    purpose: Mapped[CapabilityPurpose] = mapped_column(String(), primary_key=True)
    is_default_enabled: Mapped[bool] = mapped_column(server_default="true")
    __table_args__ = (
        CheckConstraint(
            "purpose IN ('web_search', 'image_generation')",
            name="ck_policy_capability_purpose",
        ),
    )
