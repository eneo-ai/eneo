"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Banner } from "@astryxdesign/core/Banner";
import { Button } from "@astryxdesign/core/Button";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useQueries } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { useId, useRef, type ReactNode } from "react";
import { ClientTime } from "@/components/composites/client-time";
import { PageHeader } from "@/components/composites/page-header";
import { useAppContext } from "@/components/providers/app-context";
import { RemovalFocusScope } from "@/features/spaces/removal";
import { useSpace } from "@/features/spaces/use-space";
import { browserApi } from "@/lib/api/browser";
import { hoursUntil } from "@/lib/format";
import { useHydrated } from "@/lib/hooks/use-hydrated";
import type { IntegrationKnowledge } from "../../knowledge";
import { IntegrationActions, WrapperActions } from "../actions";
import { skippedDocumentsQueryOptions } from "../queries";
import { buildSourceProblems, type SkippedDocuments } from "../source-problems";
import {
  sourceContentsLabel,
  sourceHref,
  summarizeSource,
  type IntegrationSource,
  type SourceTab
} from "../sources";
import { useSyncProgress } from "../use-sync-progress";
import { VENDOR, VendorIcon } from "../vendor";
import { ActivityView } from "./activity-view";
import { FolderDocuments } from "./folder-documents";
import { FolderNav } from "./folder-nav";
import { FolderOverview } from "./folder-overview";
import { ProblemsView } from "./problems-view";
import { SyncProgressPanel } from "./progress-panel";

const TABS: readonly SourceTab[] = ["content", "problems", "activity"];
const EXPIRING_SOON_HOURS = 48;

function asTab(value: string | null): SourceTab {
  return TABS.find((tab) => tab === value) ?? "content";
}

/** A finished sync rewrites an item's skipped list; its timestamps say when. */
function syncRevision(item: IntegrationKnowledge): string {
  return `${item.metadata?.last_sync_attempted_at ?? ""}|${item.metadata?.last_synced_at ?? ""}`;
}

function Stat({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="border-ax-border flex flex-col gap-1 px-4 py-3 [&:not(:first-child)]:border-s max-lg:[&:nth-child(3)]:border-s-0 max-lg:[&:nth-child(n+3)]:border-t">
      <dt className="text-ax-text-secondary text-xs">{label}</dt>
      <dd className="text-sm font-semibold">{children}</dd>
    </div>
  );
}

/** Whether SharePoint tells Eneo about changes: how many items are watched, and what lapsed. */
function WatchStat({ items }: { items: IntegrationKnowledge[] }) {
  const t = useTranslations();
  const hydrated = useHydrated();
  // Expiry is relative to now, which the server and the browser see differently.
  if (!hydrated) return <>–</>;
  const hours = items.map((item) => {
    const expires = item.metadata?.sharepoint_subscription_expires_at;
    return expires ? hoursUntil(expires) : null;
  });
  const watched = hours.filter((left) => left !== null && left > 0).length;
  const expired = hours.filter((left) => left !== null && left <= 0).length;
  const expiring = hours.filter(
    (left) => left !== null && left > 0 && left <= EXPIRING_SOON_HOURS
  ).length;
  const label =
    watched === items.length
      ? t("integration_source_watch_on")
      : watched === 0
        ? t("integration_source_watch_off")
        : t("integration_source_watch_partial", { count: watched, total: items.length });
  return (
    <span className="flex flex-col gap-0.5">
      {label}
      {expired > 0 ? (
        <span className="text-ax-warning text-xs font-normal">
          {t("integration_source_watch_expired", { count: expired })}
        </span>
      ) : expiring > 0 ? (
        <span className="text-ax-text-secondary text-xs font-normal">
          {t("integration_source_watch_expiring", { count: expiring })}
        </span>
      ) : watched === 0 ? (
        <span className="text-ax-text-secondary text-xs font-normal">
          {t("integration_source_watch_off_hint")}
        </span>
      ) : null}
    </span>
  );
}

/**
 * One source (a wrapper of folders, or a single item): what it holds and how
 * its syncs go. Contents lists folders and documents, Problems says what went
 * wrong and who fixes it, Activity is the sync history. The tab and the folder
 * live in the address (?tab=, ?folder=), so links and reloads keep them.
 */
export function SourcePage({ source }: { source: IntegrationSource }) {
  const t = useTranslations();
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const { space, routeId } = useSpace();
  const { can } = useAppContext();
  const hydrated = useHydrated();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const baseId = useId();
  const panelId = `${baseId}-panel`;
  const tabId = (tab: SourceTab) => `${baseId}-tab-${tab}`;

  const progress = useSyncProgress();
  const summary = summarizeSource(source.items, progress);
  const multiple = source.items.length > 1;
  const singleItem = multiple ? null : (source.items[0] ?? null);
  const tab = asTab(searchParams.get("tab"));
  const requested = searchParams.get("folder");
  const selectedItem = multiple
    ? (source.items.find((item) => item.id === requested) ?? null)
    : singleItem;

  const skippedQueries = useQueries({
    queries: source.items.map((item) =>
      skippedDocumentsQueryOptions(browserApi, space.id, item.id, syncRevision(item))
    )
  });
  // undefined while an item's list loads, null when it could not be loaded.
  const skippedByItem: Record<string, SkippedDocuments | null | undefined> = Object.fromEntries(
    source.items.map((item, index) => {
      const query = skippedQueries[index];
      return [item.id, query?.isError ? null : query?.data];
    })
  );
  const skippedLoaded = skippedQueries.every((query) => !query.isPending);
  const problems = skippedLoaded ? buildSourceProblems(source.items, skippedByItem, t) : null;
  // Before the skipped lists arrive, the failures alone already give the blocking causes.
  const problemCount = (problems ?? buildSourceProblems(source.items, {}, t)).causeCount;
  const skippedTotal = skippedLoaded
    ? Object.values(skippedByItem).reduce((sum, skipped) => sum + (skipped?.total ?? 0), 0)
    : null;

  const listHref = `/spaces/${routeId}/knowledge?tab=integrations`;
  const problemsHref = sourceHref(routeId, source, { tab: "problems" });
  const adminIntegrationsUrl = hydrated
    ? new URL("/admin/integrations", window.location.origin).href
    : "/admin/integrations";
  const owned = source.items.filter((item) => item.space_id === space.id);
  const permissions =
    owned.length === source.items.length ? (owned[0]?.permissions ?? []) : ([] as string[]);
  const firstSync = source.items.every((item) => !item.metadata?.last_synced_at);
  // A folder's own feed already names its file, so only the overview lists them here.
  const nowReading =
    !multiple || selectedItem
      ? []
      : source.items.flatMap((item) => {
          const current = progress[item.id]?.current;
          return current ? [{ folder: item.name, file: current }] : [];
        });

  function selectTab(next: string) {
    const params = new URLSearchParams(searchParams.toString());
    params.set("tab", asTab(next));
    router.replace(`${pathname}?${params.toString()}`, { scroll: false });
  }

  const folderHref = (itemId: string | null) => sourceHref(routeId, source, { folder: itemId });
  // From another tab the link must name the content tab, or the tab stays put.
  const folderContentHref = (itemId: string) =>
    sourceHref(routeId, source, { folder: itemId, tab: "content" });

  const actions =
    source.kind === "wrapper" ? (
      permissions.includes("edit") || permissions.includes("delete") ? (
        <WrapperActions
          wrapperId={source.id}
          wrapperName={source.name}
          itemCount={source.items.length}
          canEdit={permissions.includes("edit")}
          canDelete={permissions.includes("delete")}
          onDeleted={() => router.push(listHref)}
        />
      ) : null
    ) : singleItem ? (
      <IntegrationActions item={singleItem} />
    ) : null;

  return (
    <RemovalFocusScope target={headingRef}>
      <div className="flex w-full flex-col gap-5">
        <PageHeader
          title={source.name}
          headingRef={headingRef}
          breadcrumbs={[
            { label: t("integrations"), href: listHref },
            { label: source.name, current: true }
          ]}
          actions={
            <div className="flex items-center gap-2">
              {singleItem?.url ? (
                <Button
                  label={t(VENDOR[singleItem.integration_type].linkLabel)}
                  href={singleItem.url}
                  target="_blank"
                  icon={<ExternalLink className="size-4" aria-hidden="true" />}
                />
              ) : null}
              {actions}
            </div>
          }
        />

        <div className="text-ax-text-secondary flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <VendorIcon type={source.integrationType} />
          <span>{sourceContentsLabel(source.items, t)}</span>
          {singleItem?.folder_path ? (
            <>
              <span aria-hidden="true">·</span>
              <span className="break-all">{singleItem.folder_path}</span>
            </>
          ) : null}
          {singleItem?.original_name && singleItem.original_name !== singleItem.name ? (
            <>
              <span aria-hidden="true">·</span>
              <span>
                {t("integration_source_original_name", { name: singleItem.original_name })}
              </span>
            </>
          ) : null}
        </div>

        {summary.failedItems.length > 0 && tab !== "problems" ? (
          <Banner
            status="error"
            title={
              summary.credentialsFailed
                ? t("integration_source_stopped_sign_in_title")
                : summary.failedItems.length === 1
                  ? t("integration_source_failed_one")
                  : t("integration_source_failed_other", { count: summary.failedItems.length })
            }
            description={
              summary.credentialsFailed
                ? t("integration_source_stopped_sign_in_description")
                : t("integration_source_failed_description")
            }
            collapsible={false}
            endContent={
              <Button label={t("integration_source_show_problems")} size="sm" href={problemsHref} />
            }
          />
        ) : null}

        {summary.progress ? (
          <SyncProgressPanel
            progress={summary.progress}
            sourceName={source.name}
            firstSync={firstSync}
            nowReading={nowReading}
          />
        ) : (
          <dl className="border-ax-border rounded-ax-container grid grid-cols-2 border lg:grid-cols-4">
            <Stat label={t("integration_source_stat_searchable")}>
              <span className="text-xl tabular-nums">{summary.documentCount.toLocaleString()}</span>
            </Stat>
            <Stat label={t("integration_source_stat_skipped")}>
              <span className="text-xl tabular-nums">{skippedTotal ?? "–"}</span>
            </Stat>
            <Stat label={t("integration_source_last_up_to_date")}>
              {summary.lastSyncedAt ? (
                <ClientTime value={summary.lastSyncedAt} format="date_time" />
              ) : (
                "–"
              )}
            </Stat>
            <Stat label={t("integration_source_stat_watch")}>
              {source.integrationType === "sharepoint" ? <WatchStat items={source.items} /> : "–"}
            </Stat>
          </dl>
        )}

        <div className="flex flex-col gap-4">
          <TabList
            role="tablist"
            aria-label={source.name}
            value={tab}
            onChange={selectTab}
            hasDivider
          >
            <Tab
              id={tabId("content")}
              value="content"
              label={t("integration_source_tab_content")}
              panelId={panelId}
            />
            <Tab
              id={tabId("problems")}
              value="problems"
              label={t("integration_source_tab_problems")}
              panelId={panelId}
              endContent={
                problemCount > 0 ? (
                  <Badge variant="error" label={String(problemCount)} />
                ) : undefined
              }
            />
            <Tab
              id={tabId("activity")}
              value="activity"
              label={t("integration_source_tab_activity")}
              panelId={panelId}
            />
          </TabList>
          {/* One panel whose content follows the tab, so every tab's aria-controls exists. */}
          <div role="tabpanel" id={panelId} aria-labelledby={tabId(tab)} className="min-w-0">
            {tab === "content" ? (
              multiple ? (
                <div className="flex flex-wrap items-start gap-6">
                  <div className="max-w-72 min-w-0 flex-[1_1_14rem]">
                    <FolderNav
                      items={source.items}
                      progress={progress}
                      selectedId={selectedItem?.id ?? null}
                      hrefFor={folderHref}
                    />
                  </div>
                  <div className="min-w-0 flex-[999_1_32rem]">
                    {selectedItem ? (
                      <FolderDocuments
                        key={selectedItem.id}
                        item={selectedItem}
                        progress={progress}
                        skipped={skippedByItem[selectedItem.id] ?? null}
                        problemsHref={problemsHref}
                      />
                    ) : (
                      <FolderOverview
                        items={source.items}
                        progress={progress}
                        sourceName={source.name}
                        hrefFor={folderHref}
                      />
                    )}
                  </div>
                </div>
              ) : singleItem ? (
                <FolderDocuments
                  key={singleItem.id}
                  item={singleItem}
                  progress={progress}
                  skipped={skippedByItem[singleItem.id] ?? null}
                  problemsHref={problemsHref}
                  showHeader={source.kind === "wrapper"}
                />
              ) : null
            ) : tab === "problems" ? (
              <ProblemsView
                problems={problems}
                isAdmin={can("admin")}
                adminIntegrationsUrl={adminIntegrationsUrl}
                folderHref={folderContentHref}
                showFolders={multiple}
                onRetry={() => {
                  for (const query of skippedQueries) if (query.isError) void query.refetch();
                }}
              />
            ) : (
              // Each folder's history is a request of its own; only fetch it when it is looked at.
              <ActivityView items={source.items} showFolders={multiple} />
            )}
          </div>
        </div>
      </div>
    </RemovalFocusScope>
  );
}
