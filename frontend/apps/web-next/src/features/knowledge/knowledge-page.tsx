"use client";

import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useTranslations } from "next-intl";
import { useSearchParams } from "next/navigation";
import { useId, useRef, useState } from "react";
import { PageHeader } from "@/components/composites/page-header";
import { RemovalFocusScope } from "@/features/spaces/removal";
import type { SpaceResource } from "@/features/spaces/space";
import { useSpace } from "@/features/spaces/use-space";
import { CollectionsTab } from "./collections";
import { IntegrationsTab } from "./integrations/tab";
import { WebsitesTab } from "./websites";

type KnowledgeTab = "collections" | "websites" | "integrations";

/** The tabs in order, each with the resource it lists (read to see it, create to add). */
const KNOWLEDGE_TABS: { id: KnowledgeTab; resource: SpaceResource }[] = [
  { id: "collections", resource: "collection" },
  { id: "websites", resource: "website" },
  { id: "integrations", resource: "integrationKnowledge" }
];

/**
 * The space knowledge hub: collections / websites / integrations as Astryx
 * tabs (the WAI-ARIA tabs pattern), each gated by the corresponding read
 * permission. The active tab lives in ?tab= so links can target one
 * directly. The one tab panel takes focus when a row inside is deleted or
 * moved away.
 */
export function KnowledgePage({
  integrationRequestFormUrl
}: {
  integrationRequestFormUrl?: string;
}) {
  const t = useTranslations();
  const { can } = useSpace();
  const searchParams = useSearchParams();
  const baseId = useId();
  const panelRef = useRef<HTMLDivElement>(null);

  const tabs = KNOWLEDGE_TABS.filter((tab) => can("read", tab.resource)).map((tab) => tab.id);
  const requested = searchParams.get("tab");
  const [tab, setTab] = useState<KnowledgeTab>(
    tabs.find((id) => id === requested) ?? tabs[0] ?? "collections"
  );

  function selectTab(next: KnowledgeTab) {
    setTab(next);
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    window.history.replaceState(null, "", url);
  }

  const panelId = `${baseId}-panel`;
  const tabId = (id: KnowledgeTab) => `${baseId}-tab-${id}`;

  return (
    <div className="flex w-full flex-col gap-6">
      <PageHeader
        headingLevel={2}
        title={t("knowledge")}
        description={t("space_knowledge_description")}
      />
      {tabs.length > 0 ? (
        <div className="flex flex-col gap-4">
          <TabList
            role="tablist"
            aria-label={t("space_knowledge_tabs_label")}
            value={tab}
            onChange={(value) => selectTab(value as KnowledgeTab)}
            hasDivider
          >
            {tabs.map((id) => (
              <Tab key={id} id={tabId(id)} value={id} label={t(id)} panelId={panelId} />
            ))}
          </TabList>
          <div
            ref={panelRef}
            role="tabpanel"
            id={panelId}
            aria-labelledby={tabId(tab)}
            tabIndex={-1}
            className="focus-visible:outline-ring rounded-ax-element focus-visible:outline-2 focus-visible:outline-offset-4"
          >
            <RemovalFocusScope target={panelRef}>
              {tab === "collections" ? (
                <CollectionsTab
                  canCreate={can("create", "collection")}
                  labelledBy={tabId("collections")}
                />
              ) : tab === "websites" ? (
                <WebsitesTab canCreate={can("create", "website")} labelledBy={tabId("websites")} />
              ) : (
                <IntegrationsTab
                  canCreate={can("create", "integrationKnowledge")}
                  integrationRequestFormUrl={integrationRequestFormUrl}
                  labelledBy={tabId("integrations")}
                />
              )}
            </RemovalFocusScope>
          </div>
        </div>
      ) : null}
    </div>
  );
}
