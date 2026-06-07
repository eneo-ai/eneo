"""Space-scoped website/crawl capabilities."""

from __future__ import annotations

from typing import Optional, cast
from uuid import UUID

from pydantic import BaseModel, Field

from intric.audit.domain.action_types import ActionType
from intric.audit.domain.entity_types import EntityType
from intric.config_capabilities.capability import (
    CapabilityContext,
    CapabilityResult,
    ConfigCapability,
    Scope,
)
from intric.config_capabilities.registry import register
from intric.websites.domain.crawl_run import CrawlType
from intric.websites.domain.website import UpdateInterval


class CreateWebsiteInput(BaseModel):
    url: str = Field(description="URL to crawl.")
    name: Optional[str] = Field(default=None, description="Optional display name.")


async def _create_website(ctx: CapabilityContext, inp: BaseModel) -> CapabilityResult:
    data = cast(CreateWebsiteInput, inp)
    website = await ctx.container.website_crud_service().create_website(
        space_id=cast(UUID, ctx.space.id),
        url=data.url,
        name=data.name,
        download_files=False,
        crawl_type=CrawlType.CRAWL,
        update_interval=UpdateInterval.NEVER,
    )
    return CapabilityResult(
        summary=f"Created website '{website.url}' and started a crawl.",
        entity_id=website.id,
    )


register(
    ConfigCapability(
        id="website.create",
        scope=Scope.SPACE,
        input_model=CreateWebsiteInput,
        permission=lambda actor: actor.can_create_websites(),
        handler=_create_website,
        title_en="Add website",
        title_sv="Lägg till webbplats",
        description="Add a website as knowledge and start crawling it.",
        audit_action=ActionType.WEBSITE_CREATED,
        audit_entity=EntityType.WEBSITE,
        confirm_summary_en="add and crawl the website '{url}'",
        confirm_summary_sv="lägg till och crawla webbplatsen '{url}'",
        form_renderable=True,
    )
)
