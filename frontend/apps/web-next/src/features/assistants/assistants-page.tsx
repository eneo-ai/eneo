"use client";

import { Bot, SearchX } from "lucide-react";
import { useTranslations } from "next-intl";
import { useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { RESOURCE_GRID_CLASS } from "@/components/composites/resource-tile";
import { SpaceSectionHeader } from "@/features/spaces/frame/space-section-header";
import { filterSpaceResources } from "@/features/spaces/resource-filter";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";
import { useSpace } from "@/features/spaces/use-space";
import { spaceChatItems, type ChatAppItem } from "./assistants";
import { CreateChatAppMenu } from "./create-menu";
import { ChatAppTile } from "./tile";

function TileGrid({ items, showStatus }: { items: ChatAppItem[]; showStatus: boolean }) {
  return (
    <ul className={RESOURCE_GRID_CLASS}>
      {items.map((item) => (
        <li key={item.id} className="min-w-0">
          <ChatAppTile item={item} showStatus={showStatus} />
        </li>
      ))}
    </ul>
  );
}

/**
 * Assistants and group chats in one grid; grouped into published/drafts for
 * users who can publish (matching the Svelte table groups).
 */
export function AssistantsPage() {
  const t = useTranslations();
  const { space, can } = useSpace();
  const [filter, setFilter] = useState("");

  const items = spaceChatItems(space);
  const filteredItems = filterSpaceResources(items, filter);
  const showStatus = !space.personal;
  const groupByStatus = can("publish", "assistant");
  const canCreate = can("create", "assistant");
  const published = filteredItems.filter((item) => item.published);
  const drafts = filteredItems.filter((item) => !item.published);

  return (
    <div className="flex w-full flex-col gap-6">
      <SpaceSectionHeader
        title={t("assistants")}
        actions={canCreate && items.length > 0 ? <CreateChatAppMenu /> : undefined}
      />
      {items.length === 0 ? (
        <EmptyState
          icon={<Bot />}
          title={t("space_assistants_empty_title")}
          description={t("space_assistants_empty_description")}
          actions={canCreate ? <CreateChatAppMenu /> : undefined}
        />
      ) : (
        <>
          <ResourceFilterInput
            value={filter}
            onChange={setFilter}
            placeholder={t("filter_assistants_placeholder")}
          />
          {filteredItems.length === 0 ? (
            <EmptyState icon={<SearchX />} title={t("no_results_found")} isCompact />
          ) : groupByStatus ? (
            <div className="flex flex-col gap-6">
              {published.length > 0 && (
                <section aria-labelledby="assistants-published" className="flex flex-col gap-3">
                  <h3
                    id="assistants-published"
                    className="text-ax-text-secondary text-sm font-semibold"
                  >
                    {t("published")}
                  </h3>
                  <TileGrid items={published} showStatus={false} />
                </section>
              )}
              {drafts.length > 0 && (
                <section aria-labelledby="assistants-drafts" className="flex flex-col gap-3">
                  <h3
                    id="assistants-drafts"
                    className="text-ax-text-secondary text-sm font-semibold"
                  >
                    {t("drafts")}
                  </h3>
                  <TileGrid items={drafts} showStatus={false} />
                </section>
              )}
            </div>
          ) : (
            <TileGrid items={filteredItems} showStatus={showStatus} />
          )}
        </>
      )}
    </div>
  );
}
