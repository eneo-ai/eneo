"use client";

import { SegmentedControl, SegmentedControlItem } from "@astryxdesign/core/SegmentedControl";
import { Selector } from "@astryxdesign/core/Selector";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useTranslations } from "next-intl";
import { replaceUrl, useSearchParams } from "@/lib/navigation";
import { useId, useRef } from "react";
import type { TableName } from "@/components/astryx/table";
import { PageHeader } from "@/components/composites/page-header";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
import { RemovalFocusScope } from "@/features/spaces/removal";
import { useSpace } from "@/features/spaces/use-space";
import { CollectionsTab } from "./collections";
import { KnowledgeActionScope } from "./knowledge-action-scope";
import { IntegrationsTab } from "./integrations/tab";
import { WebsitesTab } from "./websites";
import { KNOWLEDGE_TABS, readKnowledgeTab, type KnowledgeTab } from "./knowledge";

/**
 * The space knowledge hub: collections / websites / integrations as Astryx
 * tabs (the WAI-ARIA tabs pattern), each gated by the corresponding read
 * permission. The active tab lives in ?tab= so links can target one
 * directly. The one tab panel takes focus when a row inside is deleted or
 * moved away.
 *
 * On a phone (decision 9, the artifact's Kunskap board) the source is a mode
 * of one list: a segmented control under the space's own tabs, not a second
 * tab strip, and each source lists rows. The heading and description stay
 * for screen readers; the space header above names the page. Where the
 * three labels do not fit whole (under 20.5rem of content: about 360 px at
 * the default text size, or larger text) the source is a select. No tabs on
 * a phone, so the panel and lists are named by the source's name, not by a
 * hidden tab. Until the width is known both switchers render and CSS shows
 * one.
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
  const phone = useMediaMatch(PHONE_QUERY);

  const tabs = KNOWLEDGE_TABS.filter((tab) => can("read", tab.resource)).map((tab) => tab.id);
  const tab = readKnowledgeTab(searchParams, tabs);

  function selectTab(next: KnowledgeTab) {
    const url = new URL(window.location.href);
    url.searchParams.set("tab", next);
    replaceUrl(url);
  }

  const panelId = `${baseId}-panel`;
  const tabId = (id: KnowledgeTab) => `${baseId}-tab-${id}`;
  // What names a source's table or list: its tab, or on a phone its name.
  const name = (id: KnowledgeTab): TableName =>
    phone ? { "aria-label": t(id) } : { "aria-labelledby": tabId(id) };

  return (
    <div className="flex w-full flex-col gap-6">
      <PageHeader
        headingLevel={2}
        title={t("knowledge")}
        description={t("space_knowledge_description")}
        className="max-md:sr-only"
      />
      {tabs.length > 0 ? (
        <div className="@container flex flex-col gap-4">
          {phone !== false ? (
            <div className="md:hidden">
              <div className="hidden @min-[20.5rem]:block [&_[role=radio]]:px-1.5">
                <SegmentedControl
                  label={t("space_knowledge_tabs_label")}
                  value={tab}
                  onChange={(value) => selectTab(value as KnowledgeTab)}
                  layout="fill"
                  size="lg"
                >
                  {tabs.map((id) => (
                    <SegmentedControlItem key={id} value={id} label={t(id)} />
                  ))}
                </SegmentedControl>
              </div>
              <div className="@min-[20.5rem]:hidden">
                <Selector
                  label={t("space_knowledge_tabs_label")}
                  isLabelHidden
                  options={tabs.map((id) => ({ value: id, label: t(id) }))}
                  value={tab}
                  onChange={(value) => selectTab(value as KnowledgeTab)}
                  width="100%"
                />
              </div>
            </div>
          ) : null}
          {phone !== true ? (
            <div className="max-md:hidden">
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
            </div>
          ) : null}
          <div
            ref={panelRef}
            id={panelId}
            {...(phone
              ? { role: "group", "aria-label": t(tab) }
              : { role: "tabpanel", "aria-labelledby": tabId(tab) })}
            tabIndex={-1}
            className="focus-visible:outline-ring rounded-ax-element focus-visible:outline-2 focus-visible:outline-offset-4"
          >
            <RemovalFocusScope target={panelRef}>
              <KnowledgeActionScope key={tab} focusTarget={panelRef}>
                {tab === "collections" ? (
                  <CollectionsTab
                    canCreate={can("create", "collection")}
                    name={name("collections")}
                  />
                ) : tab === "websites" ? (
                  <WebsitesTab canCreate={can("create", "website")} name={name("websites")} />
                ) : (
                  <IntegrationsTab
                    canCreate={can("create", "integrationKnowledge")}
                    integrationRequestFormUrl={integrationRequestFormUrl}
                    name={name("integrations")}
                  />
                )}
              </KnowledgeActionScope>
            </RemovalFocusScope>
          </div>
        </div>
      ) : null}
    </div>
  );
}
