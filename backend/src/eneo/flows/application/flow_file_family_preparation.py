"""Prepare one bounded, locked file family before any ownership is released."""

from dataclasses import dataclass
from uuid import UUID

from eneo.data_retention.application.retention_units import (
    RetentionUnitDisposition,
    RetentionUnitUsage,
)
from eneo.data_retention.domain.retention import ReceiptReason
from eneo.flows.infrastructure.flow_file_family_repo import (
    FamilyMember,
    FlowFileFamilyRepository,
)


@dataclass(frozen=True, slots=True)
class PreparedFileFamily:
    members: tuple[FamilyMember, ...]
    manifest: tuple[tuple[UUID, UUID], ...]
    bound_transcripts: int
    examined_rows: int
    total_rows: int
    total_files: int


@dataclass(frozen=True, slots=True)
class FileFamilyPreparationStopped:
    usage: RetentionUnitUsage
    pause_reason: ReceiptReason | None = None


async def prepare_file_family(
    repository: FlowFileFamilyRepository,
    root: UUID,
    *,
    rows: int,
    files: int,
    cap: int,
    initial_rows: int,
) -> PreparedFileFamily | FileFamilyPreparationStopped:
    """Bound counts, complete fit, locked growth and depth before manifest writes.

    The caller has already charged its admission/owner reads in initial_rows.
    The full reservation includes one FRESH owner check per member, the depth
    predicate and potential binding, reference, transcript and member deletions.
    The caller checks external owners immediately before releasing the graph.
    No prepared family survives its transaction.
    """
    used = initial_rows

    def defer() -> FileFamilyPreparationStopped:
        return FileFamilyPreparationStopped(
            RetentionUnitUsage(
                rows=used, files=0, disposition=RetentionUnitDisposition.DOES_NOT_FIT
            )
        )

    def over_cap() -> FileFamilyPreparationStopped:
        return FileFamilyPreparationStopped(
            RetentionUnitUsage(rows=used, files=0),
            ReceiptReason.FAMILY_EXCEEDS_BUDGET,
        )

    if cap <= used:
        return over_cap()
    if rows <= used:
        return defer()

    def room(maximum: int) -> int:
        # The sentinel itself must fit the remaining examined-row allowance.
        return max(0, min(maximum, rows - used - 1))

    fixed = initial_rows + 1
    member_max = (cap - fixed) // 4
    limit = room(member_max)
    members = await repository.count_members(root, limit=limit + 1)
    used += members
    if members > member_max:
        return over_cap()
    if members > limit:
        return defer()

    reference_max = (cap - fixed - 4 * members) // 2
    limit = room(reference_max)
    references = await repository.count_references(root, limit=limit + 1)
    used += references
    if references > reference_max:
        return over_cap()
    if references > limit:
        return defer()

    transcript_max = (cap - fixed - 4 * members - 2 * references) // 2
    limit = room(transcript_max)
    transcripts = await repository.count_bound_transcripts(root, limit=limit + 1)
    used += transcripts
    if transcripts > transcript_max:
        return over_cap()

    total_rows = fixed + 4 * members + 2 * references + 2 * transcripts
    total_files = 1 + members + 2 * references + transcripts
    if transcripts > limit or total_rows > rows or total_files > files:
        return defer()

    locked = await repository.lock_members(root, limit=members)
    used += locked.examined
    if locked.items is None:
        return FileFamilyPreparationStopped(RetentionUnitUsage(rows=used, files=0))
    manifest = await repository.manifest(locked.items, limit=references)
    used += manifest.examined
    bound = await repository.count_all_bound_transcripts(root, limit=transcripts)
    used += bound
    if manifest.items is None or bound > transcripts:
        return FileFamilyPreparationStopped(RetentionUnitUsage(rows=used, files=0))

    used += 1
    if await repository.too_deep(root) is not None:
        return FileFamilyPreparationStopped(
            RetentionUnitUsage(rows=used, files=0), ReceiptReason.FAMILY_DEPTH_EXCEEDED
        )
    return PreparedFileFamily(
        members=tuple(locked.items),
        manifest=tuple(manifest.items),
        bound_transcripts=transcripts,
        examined_rows=used,
        total_rows=total_rows,
        total_files=total_files,
    )
