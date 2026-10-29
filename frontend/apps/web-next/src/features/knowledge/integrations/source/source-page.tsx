"use client";

import { Badge } from "@astryxdesign/core/Badge";
import { Button } from "@astryxdesign/core/Button";
import { Tab, TabList } from "@astryxdesign/core/TabList";
import { useQueries, useQueryClient } from "@tanstack/react-query";
import { ExternalLink } from "lucide-react";
import { replaceUrl, useRouter, useSearchParams } from "@/lib/navigation";
import { useFormatter, useTranslations } from "use-intl";
import { useId, useRef, type ReactNode } from "react";
import { QuietBanner } from "@/components/astryx/banner";
import { ClientTime } from "@/components/composites/client-time";
import { PageHeader } from "@/components/composites/page-header";
import { useAppContext } from "@/components/providers/app-context";
import { RemovalFocusScope } from "@/features/spaces/removal";
import { useSpace } from "@/features/spaces/use-space";
import { browserApi } from "@/lib/api/browser";
import { useFocusRescue } from "@/lib/focus-rescue";
import { useHydrated } from "@/lib/hooks/use-hydrated";
import type { IntegrationKnowledge } from "../../knowledge";
import { IntegrationActions, WrapperActions } from "../actions";
import { safeExternalUrl } from "../external-url";
import { skippedDocumentsQueryOptions } from "../queries";
import { buildSourceProblems, type SkippedDocuments } from "../source-problems";
import { useWatchStates } from "../source-status";
import {
  isSyncActive,
  readSourceView,
  sourceContentsLabel,
  sourceHref,
  sourceTabParam,
  summarizeSource,
  wrapperPermissions,
  type IntegrationSource,
  type SourceTab,
  type SourceView
} from "../sources";
import { useSourceAnnouncements } from "../use-sync-announcements";
import { useSyncProgress } from "../use-sync-progress";
import { VENDOR, VendorIcon } from "../vendor";
import { ActivityView } from "./activity-view";
import { FolderDocuments } from "./folder-documents";
import { FolderNav } from "./folder-nav";
import { FolderOverview } from "./folder-overview";
import { inPlaceLink, SamePageLink } from "@/components/composites/in-place-link";
import { ProblemsView } from "./problems-view";
import { SyncProgressPanel } from "./progress-panel";

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
  const states = useWatchStates(items);
  if (!states) return <>–</>;
  const expired = states.filter((state) => state === "expired").length;
  const expiring = states.filter((state) => state === "expiring").length;
  const watched = states.filter((state) => state === "active" || state === "expiring").length;
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
          {expired === 1
            ? t("integration_source_watch_expired_one")
            : t("integration_source_watch_expired_other", { count: expired })}
        </span>
      ) : expiring > 0 ? (
        <span className="text-ax-text-secondary text-xs font-normal">
          {expiring === 1
            ? t("integration_source_watch_expiring_one")
            : t("integration_source_watch_expiring_other", { count: expiring })}
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
 * live in the address (?tab=, ?folder=), so links and reloads keep them; a
 * change only rewrites the address, it does not load the page again. The
 * sync's course and a changed problem count are announced.
 */
export function SourcePage({ source }: { source: IntegrationSource }) {
  const t = useTranslations();
  const format = useFormatter();
  const router = useRouter();
  const queryClient = useQueryClient();
  const searchParams = useSearchParams();
  const { space, routeId } = useSpace();
  const { can } = useAppContext();
  const hydrated = useHydrated();
  const headingRef = useRef<HTMLHeadingElement>(null);
  const baseId = useId();
  const panelId = `${baseId}-panel`;
  const tabId = (tab: SourceTab) => `${baseId}-tab-${tab}`;
  const rescue = useFocusRescue();
  // By id, not a ref: the in-place links that call it are built during render (react-hooks/refs).
  const focusPanelIfLost = () => rescue(document.getElementById(panelId));
  const view = readSourceView(searchParams);
  const { tab } = view;

  const { progress, queued, loaded: progressLoaded } = useSyncProgress();
  const summary = summarizeSource(source.items, progress, queued);
  const syncActive = isSyncActive(summary);
  const multiple = source.items.length > 1;
  const singleItem = multiple ? null : (source.items[0] ?? null);
  const selectedItem = multiple
    ? (source.items.find((item) => item.id === view.folder) ?? null)
    : singleItem;

  // Keyed by each item's sync revision; the list shown before stays while a
  // new one loads, so Problems keeps its place.
  const skippedQueries = useQueries({
    queries: source.items.map((item) =>
      skippedDocumentsQueryOptions(browserApi, queryClient, space.id, item)
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
  // Over the current items: a removed folder's list stays in the cache a while.
  const skippedTotal = skippedLoaded
    ? source.items.reduce((sum, item) => sum + (skippedByItem[item.id]?.total ?? 0), 0)
    : null;
  useSourceAnnouncements(
    source.name,
    progressLoaded ? summary : null,
    problems ? problemCount : null
  );

  const listHref = `/spaces/${routeId}/knowledge?tab=integrations`;
  const adminIntegrationsUrl = hydrated
    ? new URL("/admin/integrations", window.location.origin).href
    : "/admin/integrations";
  const { canEdit, canDelete } = wrapperPermissions(source.items, space.id);
  const firstSync = source.items.every((item) => !item.metadata?.last_synced_at);
  // A folder's own feed already names its file, so only the overview lists them here.
  const nowReading =
    !multiple || selectedItem
      ? []
      : source.items.flatMap((item) => {
          const current = progress[item.id]?.current;
          return current ? [{ folder: item.name, file: current }] : [];
        });

  // Like the knowledge page's tabs: the address follows, without a server round trip.
  function show(next: SourceView) {
    const url = new URL(window.location.href);
    if (next.tab === "content") url.searchParams.delete("tab");
    else url.searchParams.set("tab", next.tab);
    if (next.folder) url.searchParams.set("folder", next.folder);
    else url.searchParams.delete("folder");
    replaceUrl(url);
    // The link that was pressed may have gone with the old view; a folder picked
    // from the overview takes focus at its heading, anything else at the panel.
    const folderHeading =
      next.tab === "content" && next.folder && next.folder !== view.folder
        ? `folder-documents-${next.folder}`
        : null;
    rescue(
      () =>
        (folderHeading ? document.getElementById(folderHeading) : null) ??
        document.getElementById(panelId)
    );
  }

  const linkTo = (next: SourceView) =>
    inPlaceLink(
      sourceHref(routeId, source, {
        folder: next.folder,
        tab: next.tab === "content" ? undefined : next.tab
      }),
      () => show(next)
    );
  const folderLink = (itemId: string | null) => linkTo({ tab: "content", folder: itemId });
  const problemsLink = linkTo({ tab: "problems", folder: view.folder });

  // Replaces the page, so Back does not lead to the source that is gone.
  const toList = () => router.replace(listHref);
  const sourceUrl = safeExternalUrl(singleItem?.url);

  const actions =
    source.kind === "wrapper" ? (
      canEdit || canDelete ? (
        <WrapperActions
          wrapperId={source.id}
          wrapperName={source.name}
          items={source.items}
          canEdit={canEdit}
          canDelete={canDelete}
          syncActive={syncActive}
          onDeleted={toList}
        />
      ) : null
    ) : singleItem ? (
      <IntegrationActions item={singleItem} syncActive={syncActive} onDeleted={toList} />
    ) : null;

  const failureTitle =
    summary.failedItems.length === 0
      ? null
      : summary.credentialsFailed
        ? t("integration_source_stopped_sign_in_title")
        : summary.failedItems.length === 1
          ? t("integration_source_failed_one")
          : t("integration_source_failed_other", { count: summary.failedItems.length });

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
              {singleItem && sourceUrl ? (
                <Button
                  label={t(VENDOR[singleItem.integration_type].linkLabel)}
                  href={sourceUrl}
                  target="_blank"
                  rel="noopener noreferrer"
                  icon={<ExternalLink className="size-4" aria-hidden="true" />}
                />
              ) : null}
              {actions}
            </div>
          }
        />

        <div className="text-ax-text-secondary flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
          <VendorIcon type={source.integrationType} />
          <span>{t(VENDOR[source.integrationType].name)}</span>
          <span aria-hidden="true">·</span>
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

        {failureTitle !== null && tab !== "problems" ? (
          <QuietBanner
            status="error"
            title={failureTitle}
            description={
              summary.credentialsFailed
                ? t("integration_source_stopped_sign_in_description")
                : t("integration_source_failed_description")
            }
            collapsible={false}
            endContent={
              <Button
                label={t("integration_source_show_problems")}
                size="sm"
                {...problemsLink}
                as={SamePageLink}
              />
            }
          />
        ) : null}

        {summary.state === "queued" && !summary.progress ? (
          <QuietBanner
            status="info"
            title={t("integration_source_queued_notice")}
            collapsible={false}
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
              <span className="text-xl tabular-nums">{format.number(summary.documentCount)}</span>
            </Stat>
            <Stat label={t("integration_source_stat_skipped")}>
              <span className="text-xl tabular-nums">
                {skippedTotal === null ? "–" : format.number(skippedTotal)}
              </span>
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
            onChange={(next) => show({ ...view, tab: sourceTabParam(next) ?? "content" })}
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
          {/* One panel whose content follows the tab, so every tab's aria-controls exists.
              It takes focus when the control that changed the view went with it. */}
          <div
            role="tabpanel"
            id={panelId}
            aria-labelledby={tabId(tab)}
            tabIndex={-1}
            className="focus-visible:outline-ring rounded-ax-element min-w-0 focus-visible:outline-2 focus-visible:outline-offset-4"
          >
            {tab === "content" ? (
              multiple ? (
                <div className="flex flex-wrap items-start gap-6">
                  <div className="max-w-72 min-w-0 flex-[1_1_14rem]">
                    <FolderNav
                      items={source.items}
                      progress={progress}
                      queued={queued}
                      selectedId={selectedItem?.id ?? null}
                      linkFor={folderLink}
                    />
                  </div>
                  <div className="min-w-0 flex-[999_1_32rem]">
                    {selectedItem ? (
                      <FolderDocuments
                        key={selectedItem.id}
                        item={selectedItem}
                        progress={progress}
                        queued={queued}
                        skipped={skippedByItem[selectedItem.id] ?? null}
                        problemsLink={problemsLink}
                      />
                    ) : (
                      <FolderOverview
                        items={source.items}
                        progress={progress}
                        queued={queued}
                        sourceName={source.name}
                        linkFor={folderLink}
                      />
                    )}
                  </div>
                </div>
              ) : singleItem ? (
                <FolderDocuments
                  key={singleItem.id}
                  item={singleItem}
                  progress={progress}
                  queued={queued}
                  skipped={skippedByItem[singleItem.id] ?? null}
                  problemsLink={problemsLink}
                  showHeader={source.kind === "wrapper"}
                  // The page header has the item's link and actions.
                  showControls={false}
                />
              ) : null
            ) : tab === "problems" ? (
              <ProblemsView
                problems={problems}
                isAdmin={can("admin")}
                adminIntegrationsUrl={adminIntegrationsUrl}
                folderLink={folderLink}
                showFolders={multiple}
                onRetry={() => {
                  const failed = skippedQueries.filter((query) => query.isError);
                  // Once every list loaded, the retry button is gone.
                  void Promise.all(failed.map((query) => query.refetch())).then(focusPanelIfLost);
                }}
              />
            ) : (
              // Each folder's history is a request of its own; only fetch it when it is looked at.
              <ActivityView
                spaceId={space.id}
                items={source.items}
                selectedId={multiple ? (selectedItem?.id ?? null) : null}
                onSelect={(folder) => show({ tab: "activity", folder })}
              />
            )}
          </div>
        </div>
      </div>
    </RemovalFocusScope>
  );
}
