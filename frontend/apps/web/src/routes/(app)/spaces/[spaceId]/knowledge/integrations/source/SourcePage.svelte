<script lang="ts">
  import { tick, untrack } from "svelte";
  import { get, writable } from "svelte/store";
  import { goto } from "$app/navigation";
  import { page } from "$app/state";
  import { resolve } from "$app/paths";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconLinkExternal } from "@eneo/icons/link-external";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Page } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getAppContext } from "$lib/core/AppContext";
  import { getEneo } from "$lib/core/Eneo";
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import { previewLinkLabel } from "$lib/features/integrations/IntegrationData";
  import IntegrationVendorIcon from "$lib/features/integrations/components/IntegrationVendorIcon.svelte";
  import type { IntegrationSkippedDocuments } from "$lib/features/integrations/integrationDocuments";
  import { safeExternalUrl } from "$lib/features/integrations/externalUrl";
  import { buildSourceProblems } from "$lib/features/integrations/sourceProblems";
  import {
    isSyncActive,
    itemWatchState,
    sourceContentsLabel,
    sourceHref,
    summarizeSource,
    type IntegrationSource
  } from "$lib/features/integrations/sources";
  import {
    announceProblemCount,
    SourceAnnouncer
  } from "$lib/features/integrations/syncAnnouncements";
  import { useSyncProgress } from "$lib/features/integrations/useSyncProgress.svelte";
  import { jobCompletionEvents } from "$lib/features/jobs/JobManager";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import SourceStat from "$lib/features/knowledge/components/SourceStat.svelte";
  import SourceStats from "$lib/features/knowledge/components/SourceStats.svelte";
  import { m } from "$lib/paraglide/messages";
  import IntegrationActions from "../IntegrationActions.svelte";
  import SharePointWrapperActions from "../SharePointWrapperActions.svelte";
  import FolderDocuments from "./FolderDocuments.svelte";
  import SourceActivityView from "./SourceActivityView.svelte";
  import SourceFolderNav from "./SourceFolderNav.svelte";
  import SourceFolderOverview from "./SourceFolderOverview.svelte";
  import SourceProblemsView from "./SourceProblemsView.svelte";
  import SourceProgressPanel from "./SourceProgressPanel.svelte";

  interface Props {
    source: IntegrationSource;
  }

  let { source }: Props = $props();

  const { user } = getAppContext();
  const isAdmin = user.hasPermission("admin");

  const eneo = getEneo();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  const tracker = useSyncProgress();

  // The user's own syncs report completion as jobs; refresh so counts and documents follow.
  let lastSeenJobEvent = untrack(() => get(jobCompletionEvents)?.timestamp ?? null);
  $effect(() => {
    const event = $jobCompletionEvents;
    if (!event || event.timestamp === lastSeenJobEvent) return;
    lastSeenJobEvent = event.timestamp;
    untrack(() => void refreshCurrentSpace("knowledge"));
  });
  const tab = writable<string>();

  let progress = $derived(tracker.byId);
  let queued = $derived(tracker.queued);
  let summary = $derived(summarizeSource(source.items, progress, queued));
  let syncActive = $derived(isSyncActive(summary));
  let multiple = $derived(source.items.length > 1);
  let singleItem = $derived(multiple ? null : source.items[0]);
  let singleItemUrl = $derived(safeExternalUrl(singleItem?.url));

  let selectedId = $derived.by(() => {
    if (!multiple) return source.items[0]?.id ?? null;
    const requested = page.url.searchParams.get("folder");
    return source.items.some((item) => item.id === requested) ? requested : null;
  });
  let selectedItem = $derived(source.items.find((item) => item.id === selectedId) ?? null);

  // Picking a folder in the overview replaces the overview, link and all; focus would fall to the body.
  let contentView = $state<HTMLElement | null>(null);
  let shownSelection: string | null | undefined;
  $effect(() => {
    const id = selectedId;
    if (shownSelection === undefined || id === shownSelection) {
      shownSelection = id;
      return;
    }
    shownSelection = id;
    void tick().then(() => {
      const active = document.activeElement;
      if (active && active !== document.body) return;
      contentView?.querySelector<HTMLElement>("[data-content-heading]")?.focus();
    });
  });

  // --- Skipped files, for the problems and the counts ---

  let skippedByItem = $state.raw<Record<string, IntegrationSkippedDocuments | null>>({});
  let skippedLoaded = $derived(source.items.every((item) => item.id in skippedByItem));
  // The latest request per item; an older answer for the item is dropped.
  // eslint-disable-next-line svelte/prefer-svelte-reactivity -- request bookkeeping, never rendered
  const skippedRequests = new Map<string, number>();
  let skippedRequestCount = 0;

  async function loadSkipped(items: IntegrationKnowledge[]) {
    const results = await Promise.all(
      items.map(async (item) => {
        const request = ++skippedRequestCount;
        skippedRequests.set(item.id, request);
        let skipped: IntegrationSkippedDocuments | null = null;
        try {
          skipped = (
            await eneo.integrations.knowledge.getSyncDetails({
              knowledge: item,
              space: $currentSpace,
              limit: 1
            })
          ).skipped;
        } catch (error) {
          console.error("Could not load the skipped files of an integration item", error);
        }
        return { id: item.id, request, skipped };
      })
    );
    const fresh = results.filter(({ id, request }) => skippedRequests.get(id) === request);
    if (fresh.length === 0) return;
    skippedByItem = {
      ...skippedByItem,
      ...Object.fromEntries(fresh.map(({ id, skipped }) => [id, skipped]))
    };
  }

  // A finished sync rewrites an item's skipped list and history; its timestamps say when.
  let syncSignatures = $derived(
    Object.fromEntries(
      source.items.map((item) => [
        item.id,
        `${item.metadata?.last_sync_attempted_at ?? ""}|${item.metadata?.last_synced_at ?? ""}`
      ])
    )
  );
  let seenSignatures: Record<string, string> = {};
  $effect(() => {
    const signatures = syncSignatures;
    untrack(() => {
      const changed = source.items.filter(
        (item) => seenSignatures[item.id] !== signatures[item.id]
      );
      seenSignatures = signatures;
      if (changed.length > 0) void loadSkipped(changed);
    });
  });

  let problems = $derived(skippedLoaded ? buildSourceProblems(source.items, skippedByItem) : null);
  // Before the skipped lists arrive, the failures alone already give the blocking causes.
  let problemCount = $derived((problems ?? buildSourceProblems(source.items, {})).causeCount);
  // One polite region speaks the sync's course and a changed problem count; the
  // count while syncing is throttled so a 2 s poll does not talk over the user.
  let announcement = $state("");
  const announcer = new SourceAnnouncer();
  let previousProblemCount: number | null = null;
  // Rows that never record an outcome bring no new summary; ask again when the wait ends.
  let recheck = $state(0);
  $effect(() => {
    const current = summary;
    const nextProblemCount = problems ? problemCount : null;
    void recheck;
    let timer: ReturnType<typeof setTimeout> | undefined;
    untrack(() => {
      const text = announcer.next(source.name, current, Date.now());
      const problemText = announceProblemCount(previousProblemCount, nextProblemCount);
      if (nextProblemCount !== null) previousProblemCount = nextProblemCount;
      const message = [text, problemText].filter(Boolean).join(". ");
      if (message) announcement = message;
      const until = announcer.awaitingUntil;
      if (until !== null) timer = setTimeout(() => recheck++, Math.max(0, until - Date.now()));
    });
    return () => clearTimeout(timer);
  });

  // Counted over the current items: a removed folder's list stays in skippedByItem.
  let skippedTotal = $derived(
    skippedLoaded
      ? source.items.reduce((sum, item) => sum + (skippedByItem[item.id]?.total ?? 0), 0)
      : null
  );

  // --- Change notifications (SharePoint subscriptions) ---

  let watchStates = $derived(source.items.map((item) => itemWatchState(item)));
  let expiredWatchCount = $derived(watchStates.filter((state) => state === "expired").length);
  let expiringWatchCount = $derived(watchStates.filter((state) => state === "expiring").length);
  let watchedCount = $derived(
    watchStates.filter((state) => state === "active" || state === "expiring").length
  );
  let watchLabel = $derived.by(() => {
    if (watchedCount === source.items.length) return m.integration_source_watch_on();
    if (watchedCount === 0) return m.integration_source_watch_off();
    return m.integration_source_watch_partial({
      count: watchedCount,
      total: source.items.length
    });
  });

  // --- Links and permissions ---

  let listHref = $derived(`/spaces/${$currentSpace.routeId}/knowledge?tab=integrations`);
  let adminIntegrationsUrl = $derived(`${page.url.origin}${resolve("/admin/integrations")}`);

  function folderHref(itemId: string | null): string {
    return sourceHref($currentSpace.routeId, source, { folder: itemId });
  }

  /** From another tab the link must name the content tab, or the tab stays put. */
  function folderContentHref(itemId: string): string {
    return sourceHref($currentSpace.routeId, source, { folder: itemId, tab: "content" });
  }

  function problemsHref(): string {
    return sourceHref($currentSpace.routeId, source, { tab: "problems" });
  }

  function showActivityOf(itemId: string | null) {
    const href = sourceHref($currentSpace.routeId, source, { folder: itemId, tab: "activity" });
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic space route
    void goto(href, { replaceState: true, noScroll: true, keepFocus: true });
  }

  let permissions = $derived.by(() => {
    const owned = source.items.filter((item) => item.space_id === $currentSpace.id);
    const list = owned.length === source.items.length ? (owned[0]?.permissions ?? []) : [];
    return { canEdit: list.includes("edit"), canDelete: list.includes("delete") };
  });

  let firstSync = $derived(source.items.every((item) => !item.metadata?.last_synced_at));
  // A folder's own feed already names its file, so only the overview lists them here.
  let nowReading = $derived(
    !multiple || selectedItem
      ? []
      : source.items.flatMap((item) => {
          const current = progress[item.id]?.current;
          return current ? [{ folder: item.name, file: current }] : [];
        })
  );
</script>

<svelte:head>
  <title>
    Eneo.ai – {$currentSpace.personal ? m.personal() : $currentSpace.name} – {source.name}
  </title>
</svelte:head>

<Page.Root tabController={tab}>
  <Page.Header>
    <Page.Title parents={[{ title: m.integrations(), href: listHref }]} title={source.name} truncate
    ></Page.Title>
    <Page.Tabbar>
      <Page.TabTrigger tab="content">{m.integration_source_tab_content()}</Page.TabTrigger>
      <Page.TabTrigger tab="problems">
        {m.integration_source_tab_problems()}
        {#if problemCount > 0}
          <span
            class="bg-negative-dimmer text-negative-stronger ml-1 rounded-full px-1.5 text-xs font-semibold tabular-nums"
          >
            {problemCount}
          </span>
        {/if}
      </Page.TabTrigger>
      <Page.TabTrigger tab="activity">{m.integration_source_tab_activity()}</Page.TabTrigger>
    </Page.Tabbar>
    <div class="flex-grow"></div>
    <Page.Flex>
      {#if singleItem && singleItemUrl}
        <Button variant="outline" href={singleItemUrl} target="_blank" rel="noopener noreferrer">
          {previewLinkLabel(singleItem.integration_type)}
          <IconLinkExternal size="sm" data-icon="inline-end" />
        </Button>
      {/if}
      {#if source.kind === "wrapper"}
        {#if permissions.canEdit || permissions.canDelete}
          <SharePointWrapperActions
            wrapperId={source.id}
            wrapperName={source.name}
            itemCount={source.items.length}
            items={source.items}
            canEdit={permissions.canEdit}
            canDelete={permissions.canDelete}
            {syncActive}
          />
        {/if}
      {:else if singleItem}
        <IntegrationActions knowledgeItem={singleItem} {syncActive} />
      {/if}
    </Page.Flex>
  </Page.Header>

  <Page.Main>
    <p class="sr-only" role="status" aria-live="polite">{announcement}</p>
    <div class="flex flex-col gap-5 py-4 pr-4">
      <div class="text-secondary flex flex-wrap items-center gap-x-2 gap-y-1 text-sm">
        <IntegrationVendorIcon size="sm" type={source.integrationType} />
        <span>{sourceContentsLabel(source.items)}</span>
        {#if singleItem?.folder_path}
          <span aria-hidden="true">·</span>
          <span class="break-all">{singleItem.folder_path}</span>
        {/if}
        {#if singleItem?.original_name && singleItem.original_name !== singleItem.name}
          <span aria-hidden="true">·</span>
          <span>{m.integration_source_original_name({ name: singleItem.original_name })}</span>
        {/if}
      </div>

      <!-- Not a live region: the page's announcement already says a sync failed, and the
           banner comes back on every tab switch. -->
      {#if summary.failedItems.length > 0 && $tab !== "problems"}
        <div
          class="border-negative-default bg-negative-dimmer text-negative-stronger flex flex-wrap items-start gap-3 rounded-lg border px-4 py-3 text-sm"
        >
          <TriangleAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
          <div class="flex min-w-0 flex-1 flex-col gap-0.5">
            <p class="font-medium">
              {summary.credentialsFailed
                ? m.integration_source_stopped_sign_in_title()
                : summary.failedItems.length === 1
                  ? m.integration_source_failed_one()
                  : m.integration_source_failed_other({ count: summary.failedItems.length })}
            </p>
            <p>
              {summary.credentialsFailed
                ? m.integration_source_stopped_sign_in_description()
                : m.integration_source_failed_description()}
            </p>
          </div>
          <Button variant="outline" size="sm" href={problemsHref()}>
            {m.integration_source_show_problems()}
          </Button>
        </div>
      {/if}

      {#if summary.state === "queued" && !summary.progress}
        <p
          class="border-accent-default bg-accent-dimmer/40 text-accent-stronger rounded-lg border px-4 py-3 text-sm"
        >
          {m.integration_source_queued_notice()}
        </p>
      {/if}

      {#if summary.progress}
        <SourceProgressPanel
          progress={summary.progress}
          sourceName={source.name}
          {firstSync}
          {nowReading}
        />
      {:else}
        <SourceStats>
          <SourceStat label={m.integration_source_stat_searchable()}>
            {summary.documentCount}
          </SourceStat>
          <SourceStat label={m.integration_source_stat_skipped()}>
            {skippedTotal ?? "–"}
          </SourceStat>
          <SourceStat label={m.integration_source_last_up_to_date()} tone="text">
            {summary.lastSyncedAt ? formatDateTime(summary.lastSyncedAt) : "–"}
          </SourceStat>
          <SourceStat label={m.integration_source_stat_watch()} tone="text">
            {source.integrationType === "sharepoint" ? watchLabel : "–"}
            {#if source.integrationType === "sharepoint"}
              {#if expiredWatchCount > 0}
                <span class="text-warning-stronger text-xs font-normal">
                  {expiredWatchCount === 1
                    ? m.integration_source_watch_expired_one()
                    : m.integration_source_watch_expired_other({ count: expiredWatchCount })}
                </span>
              {:else if expiringWatchCount > 0}
                <span class="text-secondary text-xs font-normal">
                  {expiringWatchCount === 1
                    ? m.integration_source_watch_expiring_one()
                    : m.integration_source_watch_expiring_other({ count: expiringWatchCount })}
                </span>
              {:else if watchedCount === 0}
                <span class="text-secondary text-xs font-normal">
                  {m.integration_source_watch_off_hint()}
                </span>
              {/if}
            {/if}
          </SourceStat>
        </SourceStats>
      {/if}

      <Page.Tab id="content">
        {#if multiple}
          <div class="flex flex-wrap items-start gap-6">
            <div class="max-w-72 min-w-0 flex-[1_1_14rem]">
              <SourceFolderNav
                items={source.items}
                {progress}
                {queued}
                {selectedId}
                hrefFor={folderHref}
              />
            </div>
            <div class="min-w-0 flex-[999_1_32rem]" data-focus-region bind:this={contentView}>
              {#if selectedItem}
                {#key selectedItem.id}
                  <FolderDocuments
                    knowledge={selectedItem}
                    space={$currentSpace}
                    {progress}
                    {queued}
                    skipped={skippedLoaded ? (skippedByItem[selectedItem.id] ?? null) : null}
                    problemsHref={problemsHref()}
                  />
                {/key}
              {:else}
                <SourceFolderOverview
                  items={source.items}
                  {progress}
                  {queued}
                  sourceName={source.name}
                  hrefFor={folderHref}
                />
              {/if}
            </div>
          </div>
        {:else if singleItem}
          {#key singleItem.id}
            <FolderDocuments
              knowledge={singleItem}
              space={$currentSpace}
              {progress}
              {queued}
              skipped={skippedLoaded ? (skippedByItem[singleItem.id] ?? null) : null}
              problemsHref={problemsHref()}
              showHeader={source.kind === "wrapper"}
              showControls={false}
            />
          {/key}
        {/if}
      </Page.Tab>

      <Page.Tab id="problems">
        <SourceProblemsView
          {problems}
          {isAdmin}
          {adminIntegrationsUrl}
          folderHref={folderContentHref}
          showFolders={multiple}
          onRetry={() => void loadSkipped(source.items)}
        />
      </Page.Tab>

      <Page.Tab id="activity">
        <!-- Each folder's history is a request of its own; only fetch it when it is looked at. -->
        {#if $tab === "activity"}
          <SourceActivityView
            items={source.items}
            selectedId={multiple ? selectedId : null}
            signatures={syncSignatures}
            onSelect={showActivityOf}
          />
        {/if}
      </Page.Tab>
    </div>
  </Page.Main>
</Page.Root>
