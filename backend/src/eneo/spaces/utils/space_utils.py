from uuid import UUID

from eneo.spaces.space import Space


def effective_space_ids_for(space_id: UUID, tenant_space_id: UUID | None) -> list[UUID]:
    """Space IDs whose knowledge a space sees: its own and its organization's.

    A child space (one with a tenant_space_id) also sees the collections,
    websites and integrations owned by or distributed to its organization
    space. Read access to a source is resolved in the other direction from the
    same rule (``SpaceRepository.get_info_blob_read_access``).
    """
    if tenant_space_id:
        return [space_id, tenant_space_id]
    return [space_id]


def effective_space_ids(space: Space) -> list[UUID]:
    """``effective_space_ids_for`` on a domain space."""
    return effective_space_ids_for(space.id, space.tenant_space_id)  # type: ignore[arg-type]
