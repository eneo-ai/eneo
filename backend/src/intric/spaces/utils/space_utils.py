from uuid import UUID
from intric.spaces.space import Space

def effective_space_ids(space: Space) -> list[UUID]:
    return [space.id] if not space.tenant_space_id else [space.id, space.tenant_space_id]
