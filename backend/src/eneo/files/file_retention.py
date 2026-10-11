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

    @property
    def is_refusal(self) -> bool:
        """The release refused a File it would otherwise remove.

        Every other outcome is the File's own state: deleted, still in use, gone
        already, or a derived File that its root's release owns.
        """
        return self not in {
            FileRetentionReason.DELETED,
            FileRetentionReason.IN_USE,
            FileRetentionReason.MISSING,
            FileRetentionReason.NOT_ROOT,
        }

    @property
    def rolls_back(self) -> bool:
        """The release could not finish, so the caller undoes what the unit
        already wrote: the family was held, or larger than its allowance."""
        return self in {
            FileRetentionReason.LOCKED,
            FileRetentionReason.FAMILY_EXCEEDS_BUDGET,
            FileRetentionReason.INSUFFICIENT_BUDGET,
        }

    @property
    def key(self) -> str:
        """The count name of this outcome in every retention task that reports it."""
        return f"files_{self.value}"


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
        return self.reason.rolls_back
