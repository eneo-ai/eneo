from uuid import UUID
from intric.spaces.space import Space

def effective_space_ids(space: Space) -> list[UUID]:
    """Return space IDs to query for knowledge (collections, websites, integrations).

    For child spaces (with tenant_space_id), include both the space's own ID
    and the parent org space ID so that org-level knowledge is accessible.
    """
    if space.tenant_space_id:
        return [space.id, space.tenant_space_id]
    return [space.id]
