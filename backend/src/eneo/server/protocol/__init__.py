def to_paginated_response(items: list):
    return {"items": items}


def to_paginated_response_with_public(items: list, public_items: list):
    return {
        "items": items,
        "public_count": len(public_items),
        "public_items": public_items,
    }
