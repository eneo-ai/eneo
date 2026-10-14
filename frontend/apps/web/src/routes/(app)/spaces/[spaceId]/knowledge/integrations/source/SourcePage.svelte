<script lang="ts">
  import { untrack } from "svelte";
  import { get, writable } from "svelte/store";
  import { page } from "$app/state";
  import { resolve } from "$app/paths";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconLinkExternal } from "@eneo/icons/link-external";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { Page } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import { previewLinkLabel } from "$lib/features/integrations/IntegrationData";
  import IntegrationVendorIcon from "$lib/features/integrations/components/IntegrationVendorIcon.svelte";
  import type { IntegrationSkippedDocuments } from "$lib/features/integrations/integrationDocuments";
  import { buildSourceProblems } from "$lib/features/integrations/sourceProblems";
  import {
    sourceContentsLabel,
    sourceHref,
    summarizeSource,
    type IntegrationSource
  } from "$lib/features/integrations/sources";
  import { useSyncProgress } from "$lib/features/integrations/useSyncProgress.svelte";
  import { jobCompletionEvents } from "$lib/features/jobs/JobManager";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
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
    isAdmin: boolean;
  }

  let { source, isAdmin }: Props = $props();

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
  let summary = $derived(summarizeSource(source.items, progress));
  let multiple = $derived(source.items.length > 1);
  let singleItem = $derived(multiple ? null : source.items[0]);

  let selectedId = $derived.by(() => {
    if (!multiple) return source.items[0]?.id ?? null;
    const requested = page.url.searchParams.get("folder");
    return source.items.some((item) => item.id === requested) ? requested : null;
  });
  let selectedItem = $derived(source.items.find((item) => item.id === selectedId) ?? null);

  // --- Skipped files, for the problems and the counts ---

  let skippedByItem = $state<Record<string, IntegrationSkippedDocuments | null>>({});
  let skippedLoaded = $state(false);
  let skippedGeneration = 0;

  async function loadSkipped(items: IntegrationKnowledge[]) {
    const generation = ++skippedGeneration;
    const entries = await Promise.all(
      items.map(async (item) => {
        try {
          const skipped = (await eneo.integrations.knowledge.listSkippedDocuments({
            knowledge: item,
            space: $currentSpace
          })) as IntegrationSkippedDocuments;
          return [item.id, skipped] as const;
        } catch (error) {
          console.error("Could not load the skipped files of an integration item", error);
          return [item.id, null] as const;
        }
      })
    );
    if (generation !== skippedGeneration) return;
    skippedByItem = Object.fromEntries(entries);
    skippedLoaded = true;
  }

  // A finished sync rewrites the skipped list; the timestamps say when.
  let syncSignature = $derived(
    source.items
      .map(
        (item) =>
          `${item.id}:${item.metadata?.last_sync_attempted_at ?? ""}:${item.metadata?.last_synced_at ?? ""}`
      )
      .join("|")
  );
  $effect(() => {
    void syncSignature;
    untrack(() => void loadSkipped(source.items));
  });

  let problems = $derived(skippedLoaded ? buildSourceProblems(source.items, skippedByItem) : null);
  let problemCount = $derived(
    problems?.attentionCount ?? (summary.credentialsFailed ? 1 : summary.failedItems.length)
  );
  let skippedTotal = $derived(
    skippedLoaded
      ? Object.values(skippedByItem).reduce((sum, skipped) => sum + (skipped?.total ?? 0), 0)
      : null
  );

  // --- Change notifications (SharePoint subscriptions) ---

  let watchedCount = $derived(
    source.items.filter((item) => {
      const expires = item.metadata?.sharepoint_subscription_expires_at;
      return expires ? new Date(expires).getTime() > Date.now() : false;
    }).length
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

  let permissions = $derived.by(() => {
    const owned = source.items.filter((item) => item.space_id === $currentSpace.id);
    const list = owned.length === source.items.length ? (owned[0]?.permissions ?? []) : [];
    return { canEdit: list.includes("edit"), canDelete: list.includes("delete") };
  });

  let firstSync = $derived(source.items.every((item) => !item.metadata?.last_synced_at));
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
      {#if singleItem?.url}
        <Button variant="outline" href={singleItem.url} target="_blank" rel="noopener noreferrer">
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
          />
        {/if}
      {:else if singleItem}
        <IntegrationActions knowledgeItem={singleItem} />
      {/if}
    </Page.Flex>
  </Page.Header>

  <Page.Main>
    <div class="flex flex-col gap-5 py-4 pr-4">
      <div class="text-secondary flex items-center gap-2 text-sm">
        <IntegrationVendorIcon size="sm" type={source.integrationType} />
        <span>{sourceContentsLabel(source.items)}</span>
      </div>

      {#if summary.failedItems.length > 0 && $tab !== "problems"}
        <div
          class="border-negative-default bg-negative-dimmer text-negative-stronger flex flex-wrap items-start gap-3 rounded-lg border px-4 py-3 text-sm"
          role="status"
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
          <Button variant="outline" size="sm" onclick={() => ($tab = "problems")}>
            {m.integration_source_show_problems()}
          </Button>
        </div>
      {/if}

      {#if summary.progress}
        <SourceProgressPanel progress={summary.progress} sourceName={source.name} {firstSync} />
      {:else}
        <dl class="border-default grid grid-cols-2 rounded-lg border lg:grid-cols-4">
          <div class="flex flex-col gap-1 px-4 py-3">
            <dt class="text-secondary text-xs">{m.integration_source_stat_searchable()}</dt>
            <dd class="text-xl font-semibold tabular-nums">{summary.documentCount}</dd>
          </div>
          <div class="border-default flex flex-col gap-1 border-l px-4 py-3">
            <dt class="text-secondary text-xs">{m.integration_source_stat_unreadable()}</dt>
            <dd
              class="text-xl font-semibold tabular-nums {skippedTotal
                ? 'text-warning-stronger'
                : ''}"
            >
              {skippedTotal ?? "–"}
            </dd>
          </div>
          <div class="border-default flex flex-col gap-1 px-4 py-3 max-lg:border-t lg:border-l">
            <dt class="text-secondary text-xs">{m.integration_source_last_up_to_date()}</dt>
            <dd class="pt-1 text-sm font-semibold">
              {summary.lastSyncedAt ? formatDateTime(summary.lastSyncedAt) : "–"}
            </dd>
          </div>
          <div class="border-default flex flex-col gap-1 border-l px-4 py-3 max-lg:border-t">
            <dt class="text-secondary text-xs">{m.integration_source_stat_watch()}</dt>
            <dd class="pt-1 text-sm font-semibold">
              {source.integrationType === "sharepoint" ? watchLabel : "–"}
            </dd>
          </div>
        </dl>
      {/if}

      <Page.Tab id="content">
        {#if multiple}
          <div class="flex flex-wrap items-start gap-6">
            <div class="max-w-72 min-w-0 flex-[1_1_14rem]">
              <SourceFolderNav items={source.items} {progress} {selectedId} hrefFor={folderHref} />
            </div>
            <div class="min-w-0 flex-[999_1_32rem]">
              {#if selectedItem}
                {#key selectedItem.id}
                  <FolderDocuments
                    knowledge={selectedItem}
                    space={$currentSpace}
                    {progress}
                    skippedCount={skippedLoaded
                      ? (skippedByItem[selectedItem.id]?.total ?? 0)
                      : null}
                    problemsHref={problemsHref()}
                  />
                {/key}
              {:else}
                <SourceFolderOverview
                  items={source.items}
                  {progress}
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
              skippedCount={skippedLoaded ? (skippedByItem[singleItem.id]?.total ?? 0) : null}
              problemsHref={problemsHref()}
              showHeader={false}
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
        />
      </Page.Tab>

      <Page.Tab id="activity">
        <SourceActivityView items={source.items} showFolders={multiple} />
      </Page.Tab>
    </div>
  </Page.Main>
</Page.Root>
