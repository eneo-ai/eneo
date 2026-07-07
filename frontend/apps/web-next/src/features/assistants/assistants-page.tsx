"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { filterSpaceResources } from "@/features/spaces/resource-filter";
import { ResourceFilterInput } from "@/features/spaces/resource-filter-input";
import { useSpace } from "@/features/spaces/use-space";
import { spaceChatItems, type ChatAppItem } from "./assistants";
import { CreateChatAppMenu } from "./create-menu";
import { ChatAppTile } from "./tile";

function TileGrid({ items, showStatus }: { items: ChatAppItem[]; showStatus: boolean }) {
  return (
    <div className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-4">
      {items.map((item) => (
        <ChatAppTile key={item.id} item={item} showStatus={showStatus} />
      ))}
    </div>
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
  const published = filteredItems.filter((item) => item.published);
  const drafts = filteredItems.filter((item) => !item.published);

  return (
    <div className="mx-auto flex w-full max-w-5xl flex-col gap-6">
      <PageHeader title={t("assistants")}>
        {can("create", "assistant") && <CreateChatAppMenu />}
      </PageHeader>
      {items.length === 0 ? (
        <EmptyState title={t("there_are_currently_no_assistants_configured")}>
          {can("create", "assistant") && <CreateChatAppMenu />}
        </EmptyState>
      ) : (
        <>
          <ResourceFilterInput
            value={filter}
            onChange={setFilter}
            placeholder={t("filter_assistants_placeholder")}
          />
          {filteredItems.length === 0 ? (
            <EmptyState title={t("no_results_found")} />
          ) : groupByStatus ? (
            <div className="flex flex-col gap-6">
              {published.length > 0 && (
                <section className="flex flex-col gap-2">
                  <h2 className="text-muted-foreground text-sm font-medium">{t("published")}</h2>
                  <TileGrid items={published} showStatus={false} />
                </section>
              )}
              {drafts.length > 0 && (
                <section className="flex flex-col gap-2">
                  <h2 className="text-muted-foreground text-sm font-medium">{t("drafts")}</h2>
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
