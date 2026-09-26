"use client";

import { useCollator } from "@astryxdesign/core/i18n";
import { Bot, SearchX } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useRef, useState } from "react";
import { EmptyState } from "@/components/composites/empty-state";
import { PageHeader } from "@/components/composites/page-header";
import { RESOURCE_GRID_CLASS } from "@/components/composites/resource-tile";
import { RemovalFocusScope } from "@/features/spaces/removal";
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

/** A titled group of cards (Publicerad / Utkast). */
function TileGroup({
  title,
  items,
  showStatus
}: {
  title: string;
  items: ChatAppItem[];
  showStatus: boolean;
}) {
  const headingId = useId();
  if (items.length === 0) return null;
  return (
    <section aria-labelledby={headingId} className="flex flex-col gap-3">
      <h3 id={headingId} className="text-ax-text-secondary text-sm font-semibold">
        {title}
      </h3>
      <TileGrid items={items} showStatus={showStatus} />
    </section>
  );
}

/**
 * Assistants and group chats in one grid; grouped into published/drafts for
 * users who can publish (matching the Svelte table groups).
 */
export function AssistantsPage() {
  const t = useTranslations();
  const { space, can } = useSpace();
  const collator = useCollator();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const [filter, setFilter] = useState("");

  const items = spaceChatItems(space, collator.compare);
  const filteredItems = filterSpaceResources(items, filter);
  const showStatus = !space.personal;
  const groupByStatus = can("publish", "assistant");
  const canCreate = can("create", "assistant");

  return (
    <RemovalFocusScope target={headingRef}>
      <div className="flex w-full flex-col gap-6">
        <PageHeader
          headingLevel={2}
          headingRef={headingRef}
          title={t("assistants")}
          actions={canCreate && items.length > 0 ? <CreateChatAppMenu /> : undefined}
        />
        {items.length === 0 ? (
          <EmptyState
            icon={<Bot />}
            title={t("space_assistants_empty_title")}
            description={t("space_assistants_empty_description")}
            headingLevel={3}
            actions={canCreate ? <CreateChatAppMenu /> : undefined}
          />
        ) : (
          <>
            <ResourceFilterInput
              value={filter}
              onChange={setFilter}
              label={t("space_filter_assistants_label")}
              placeholder={t("filter_assistants_placeholder")}
              resultCount={filteredItems.length}
            />
            {filteredItems.length === 0 ? (
              <EmptyState
                icon={<SearchX />}
                title={t("no_results_found")}
                headingLevel={3}
                isCompact
              />
            ) : groupByStatus ? (
              <div className="flex flex-col gap-6">
                <TileGroup
                  title={t("published")}
                  items={filteredItems.filter((item) => item.published)}
                  showStatus={false}
                />
                <TileGroup
                  title={t("drafts")}
                  items={filteredItems.filter((item) => !item.published)}
                  showStatus={false}
                />
              </div>
            ) : (
              <TileGrid items={filteredItems} showStatus={showStatus} />
            )}
          </>
        )}
      </div>
    </RemovalFocusScope>
  );
}
