from typing import TYPE_CHECKING

from intric.integration.presentation.models import (
    IntegrationPreviewData,
    IntegrationPreviewDataList,
)

if TYPE_CHECKING:
    from intric.integration.domain.entities.integration_preview import (
        IntegrationPreview,
    )


class ConfluenceContentAssembler:
    @classmethod
    def to_model(cls, item: "IntegrationPreview") -> "IntegrationPreviewData":
        return IntegrationPreviewData(
            key=item.key,
            type=item.type,
            name=item.name,
            url=item.url,
            category=item.category,
        )

    @classmethod
    def to_paginated_response(
        cls,
        items: list["IntegrationPreview"],
    ) -> IntegrationPreviewDataList:
        items = [cls.to_model(i) for i in items]
        return IntegrationPreviewDataList(items=items)
