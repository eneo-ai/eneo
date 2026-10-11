"""Results of one atomic file-family release in the caller's transaction."""

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID


class FileRetentionReason(StrEnum):
    DELETED = "deleted"
    MISSING = "missing"
    NOT_ROOT = "not_root"
    NOT_OLD_ENOUGH = "not_old_enough"
    IN_USE = "in_use"
    TENANT_MISMATCH = "tenant_mismatch"
    LOCKED = "locked"
    FAMILY_EXCEEDS_BUDGET = "family_exceeds_budget"
    INSUFFICIENT_BUDGET = "insufficient_budget"


@dataclass(frozen=True, slots=True)
class FileRetentionResult:
    """Proof/cascade rows spent and file members deleted, excluding discovery.

    The caller must roll back an enclosing conversation deletion when the
    family cannot fit; proof reads remain charged even after that rollback.
    deleted_references counts declared direct cascade dependencies of Files.
    """

    rows: int
    files: int
    deleted_roots: int
    deleted_members: int
    deleted_references: int
    tenant_id: UUID | None
    reason: FileRetentionReason

    @property
    def needs_rollback(self) -> bool:
        return self.reason in {
            FileRetentionReason.FAMILY_EXCEEDS_BUDGET,
            FileRetentionReason.INSUFFICIENT_BUDGET,
            FileRetentionReason.LOCKED,
        }
