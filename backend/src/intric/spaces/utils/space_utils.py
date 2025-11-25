from uuid import UUID
from intric.spaces.space import Space

def effective_space_ids(space: Space) -> list[UUID]:
    # Only return current space ID - do NOT include parent org space
    # Including tenant_space_id causes knowledge from org space to leak into child spaces
    return [space.id]
