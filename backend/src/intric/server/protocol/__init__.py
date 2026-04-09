from typing import TypeVar

from intric.main.models import PaginatedResponse, PaginatedResponseWithPublicItems

T = TypeVar("T")


def to_paginated_response(items: list[T]) -> PaginatedResponse[T]:
    return PaginatedResponse[T](items=items)


def to_paginated_response_with_public(
    items: list[T], public_items: list[T]
) -> PaginatedResponseWithPublicItems[T]:
    return PaginatedResponseWithPublicItems[T](
        items=items,
        public_count=len(public_items),
        public_items=public_items,
    )
