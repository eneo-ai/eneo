<script lang="ts">
  import { onDestroy, untrack } from "svelte";
  import { get } from "svelte/store";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconLinkExternal } from "@eneo/icons/link-external";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import SortButton from "$lib/components/resource-table/SortButton.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import { sanitizeLinkHref } from "$lib/components/markdown/sanitizeUrl";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage } from "$lib/core/errors";
  import { focusHandoff } from "$lib/core/focus/focusHandoff";
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import {
    DEFAULT_INTEGRATION_DOCUMENTS_QUERY,
    INTEGRATION_DOCUMENTS_QUERY_MAX_LENGTH,
    documentsPageRange,
    groupSkippedByReason,
    lastPageOffset,
    skippedDocumentsNotListed,
    toggleDocumentsSort,
    type IntegrationDocumentSort,
    type IntegrationDocumentsPage,
    type IntegrationDocumentsQuery,
    type IntegrationDocumentsTab,
    type IntegrationSkippedDocuments
  } from "$lib/features/integrations/integrationDocuments";
  import { previewLinkLabel } from "$lib/features/integrations/IntegrationData";
  import { describeSkipReason } from "$lib/features/integrations/skipReasons";
  import { summarizeIntegrationSync } from "$lib/features/integrations/syncStatus";
  import { jobCompletionEvents } from "$lib/features/jobs/JobManager";
  import BlobPreview from "$lib/features/knowledge/components/BlobPreview.svelte";
  import SourceMetadataList from "$lib/features/knowledge/components/SourceMetadataList.svelte";
  import { hasSourceMetadata } from "$lib/features/knowledge/sourceMetadata";
  import { m } from "$lib/paraglide/messages";
  import IntegrationSyncStatusCell from "../IntegrationSyncStatusCell.svelte";

  interface Props {
    knowledge: IntegrationKnowledge;
    space: { id: string };
    initialDocuments: IntegrationDocumentsPage;
    /** Null when the skipped list could not be loaded with the page. */
    initialSkipped: IntegrationSkippedDocuments | null;
    initialTab?: IntegrationDocumentsTab;
    onShowSyncHistory?: (() => void) | undefined;
  }

  let {
    knowledge,
    space,
    initialDocuments,
    initialSkipped,
    initialTab = "documents",
    onShowSyncHistory
  }: Props = $props();

  const eneo = getEneo();
  const SEARCH_DEBOUNCE_MS = 300;

  // Tab clicks reassign it; a navigation's `tab` param (a "Visa" link, history) resets it.
  let tab = $derived<string>(initialTab);
  // The query the rows and the sort headers show; a failed request leaves it as it was.
  let query = $state<IntegrationDocumentsQuery>({ ...DEFAULT_INTEGRATION_DOCUMENTS_QUERY });
  let requestedQuery: IntegrationDocumentsQuery | null = null;
  let documents = $state<IntegrationDocumentsPage>(untrack(() => initialDocuments));
  let loading = $state(false);
  let error = $state<string | null>(null);
  let searchText = $state("");
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  let loadGeneration = 0;

  let previousButton = $state<HTMLElement | null>(null);
  let nextButton = $state<HTMLElement | null>(null);

  let skipped = $state<IntegrationSkippedDocuments | null>(untrack(() => initialSkipped));
  let skippedError = $state<string | null>(null);
  let skippedLoading = $state(false);

  let summary = $derived(summarizeIntegrationSync(knowledge));
  let range = $derived(documentsPageRange(documents));
  let hasPrevious = $derived(documents.offset > 0);
  let hasNext = $derived(documents.offset + documents.items.length < documents.total_count);
  // Grouping on the translated reason also merges per-file variants of one reason.
  let skippedGroups = $derived(
    skipped
      ? groupSkippedByReason(
          skipped.items.map((item) => ({ ...item, reason: describeSkipReason(item.reason) }))
        )
      : []
  );
  let sourceLinkLabel = $derived(previewLinkLabel(knowledge.integration_type));
  let skippedNotListed = $derived(skipped ? skippedDocumentsNotListed(skipped) : 0);
  let skippedTabLabel = $derived(
    skipped
      ? m.integration_documents_skipped_tab_count({ count: skipped.total })
      : m.integration_documents_skipped_tab()
  );

  const sortColumns: { id: IntegrationDocumentSort; label: () => string }[] = [
    { id: "name", label: () => m.name() },
    { id: "path", label: () => m.integration_documents_path() },
    { id: "size", label: () => m.size() },
    { id: "updated_at", label: () => m.integration_documents_updated() }
  ];

  const ariaSort = { asc: "ascending", desc: "descending" } as const;

  async function loadDocuments(next: IntegrationDocumentsQuery) {
    const generation = ++loadGeneration;
    requestedQuery = next;
    loading = true;
    error = null;
    try {
      const page = await eneo.integrations.knowledge.listDocuments({
        knowledge,
        space,
        ...next
      });
      if (generation !== loadGeneration) return;
      // Documents deleted while paging can leave this offset past the end.
      const lastOffset = lastPageOffset(page, next.limit);
      if (page.items.length === 0 && next.offset > lastOffset) {
        return loadDocuments({ ...next, offset: lastOffset });
      }
      query = next;
      documents = page;
    } catch (err) {
      if (generation !== loadGeneration) return;
      error = getErrorMessage(err);
    } finally {
      if (generation === loadGeneration) loading = false;
    }
  }

  async function loadSkipped() {
    skippedLoading = true;
    skippedError = null;
    try {
      skipped = await eneo.integrations.knowledge.listSkippedDocuments({ knowledge, space });
    } catch (err) {
      skippedError = getErrorMessage(err);
    } finally {
      skippedLoading = false;
    }
  }

  function onSearchInput() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      const q = searchText.trim();
      if (q === query.q) return;
      void loadDocuments({ ...query, q, offset: 0 });
    }, SEARCH_DEBOUNCE_MS);
  }

  function sortBy(column: IntegrationDocumentSort) {
    void loadDocuments(toggleDocumentsSort(query, column));
  }

  async function goToPage(direction: -1 | 1) {
    // Still clickable from the keyboard while loading: the buttons stay enabled so focus stays put.
    if (loading) return;
    const [pressed, other] =
      direction === 1 ? [nextButton, previousButton] : [previousButton, nextButton];
    const handoff = focusHandoff(pressed);
    const offset = Math.max(0, documents.offset + direction * query.limit);
    await loadDocuments({ ...query, offset });
    await handoff.to(other);
  }

  // The first sync completing while the page is open should fill the table
  // without a reload; events from before the page opened are stale.
  let lastSeenEvent = untrack(() => get(jobCompletionEvents)?.timestamp ?? null);
  $effect(() => {
    const event = $jobCompletionEvents;
    if (!event || event.timestamp === lastSeenEvent) return;
    lastSeenEvent = event.timestamp;
    untrack(() => {
      void loadDocuments(query);
      void loadSkipped();
    });
  });

  onDestroy(() => clearTimeout(searchTimer));
</script>

<div class="flex flex-col gap-4 py-4 pr-4">
  <div class="flex flex-wrap items-start gap-x-8 gap-y-3">
    {#if knowledge.folder_path}
      <dl class="text-sm">
        <dt class="text-muted text-xs">{m.integration_folder_path_label()}</dt>
        <dd class="break-all">{knowledge.folder_path}</dd>
      </dl>
    {/if}
    <IntegrationSyncStatusCell {knowledge} {onShowSyncHistory} />
  </div>

  <Tabs.Root bind:value={tab}>
    <Tabs.List variant="line" aria-label={m.main_views_available_for_current_resource()}>
      <Tabs.Trigger value="documents">{m.documents()}</Tabs.Trigger>
      <Tabs.Trigger value="skipped">{skippedTabLabel}</Tabs.Trigger>
    </Tabs.List>

    <Tabs.Content value="documents" class="flex flex-col gap-3">
      <Input
        type="search"
        bind:value={searchText}
        oninput={onSearchInput}
        aria-label={m.integration_documents_search_label()}
        placeholder={m.integration_documents_search_placeholder()}
        maxlength={INTEGRATION_DOCUMENTS_QUERY_MAX_LENGTH}
        class="max-w-md"
      />

      {#if error}
        <div
          class="text-negative-stronger bg-negative-dimmer flex flex-wrap items-center gap-3 rounded p-4 text-sm"
          role="alert"
        >
          <span>{m.integration_documents_load_failed()}: {error}</span>
          <Button
            variant="outline"
            size="sm"
            onclick={() => loadDocuments(requestedQuery ?? query)}
          >
            {m.retry()}
          </Button>
        </div>
      {/if}

      {#if loading}
        <div class="text-secondary flex items-center gap-2 text-sm" role="status">
          <IconLoadingSpinner size="sm" class="animate-spin" />
          <span>{m.integration_documents_loading()}</span>
        </div>
      {/if}

      {#if documents.items.length > 0}
        <div aria-busy={loading}>
          <Table.Root aria-label={m.integration_documents_table_label({ name: knowledge.name })}>
            <Table.Header>
              <Table.Row>
                {#each sortColumns as column (column.id)}
                  {@const active = query.sort === column.id}
                  <Table.Head aria-sort={active ? ariaSort[query.order] : "none"}>
                    <SortButton
                      order={active ? query.order : undefined}
                      sortable
                      onToggle={() => sortBy(column.id)}
                    >
                      {column.label()}
                    </SortButton>
                  </Table.Head>
                {/each}
                <Table.Head>{m.integration_documents_properties()}</Table.Head>
                <Table.Head class="w-[1%]"><span class="sr-only">{m.actions()}</span></Table.Head>
              </Table.Row>
            </Table.Header>
            <Table.Body>
              {#each documents.items as document (document.id)}
                {@const sourceHref = sanitizeLinkHref(document.url)}
                <Table.Row>
                  <Table.Cell class="max-w-[28rem]">
                    <BlobPreview
                      blob={{
                        id: document.id,
                        metadata: { title: document.title },
                        source_metadata: document.source_metadata
                      }}
                      isTableView
                    />
                  </Table.Cell>
                  <Table.Cell class="text-secondary max-w-[20rem] truncate">
                    {document.relative_path}
                  </Table.Cell>
                  <Table.Cell class="tabular-nums">{formatBytes(document.size)}</Table.Cell>
                  <Table.Cell class="tabular-nums">{formatDateTime(document.updated_at)}</Table.Cell
                  >
                  <Table.Cell class="whitespace-normal">
                    {#if hasSourceMetadata(document)}
                      <SourceMetadataList
                        entries={document.source_metadata}
                        variant="inline"
                        class="text-muted-foreground text-xs"
                      />
                    {/if}
                  </Table.Cell>
                  <Table.Cell>
                    {#if sourceHref}
                      <Button
                        href={sourceHref}
                        target="_blank"
                        rel="noopener noreferrer"
                        variant="ghost"
                        size="icon-sm"
                        aria-label={sourceLinkLabel}
                      >
                        <IconLinkExternal size="sm" />
                      </Button>
                    {/if}
                  </Table.Cell>
                </Table.Row>
              {/each}
            </Table.Body>
          </Table.Root>
        </div>

        <div class="flex flex-wrap items-center justify-between gap-3 text-sm">
          <p class="text-secondary" aria-live="polite">
            {m.integration_documents_showing_range(range)}
            <span class="text-muted">
              · {m.integration_documents_total_size({ size: formatBytes(documents.total_size) })}
            </span>
          </p>
          <div class="flex gap-2">
            <!-- disabled only for a page that does not exist; while loading the buttons stay
                 focusable, since a focused button that turns disabled drops focus to the body. -->
            <Button
              bind:ref={previousButton}
              variant="outline"
              size="sm"
              disabled={!hasPrevious}
              aria-disabled={loading}
              class={loading ? "pointer-events-none opacity-50" : undefined}
              onclick={() => goToPage(-1)}
            >
              {m.previous()}
            </Button>
            <Button
              bind:ref={nextButton}
              variant="outline"
              size="sm"
              disabled={!hasNext}
              aria-disabled={loading}
              class={loading ? "pointer-events-none opacity-50" : undefined}
              onclick={() => goToPage(1)}
            >
              {m.next()}
            </Button>
          </div>
        </div>
      {:else if !loading && !error}
        <div class="text-secondary flex flex-col items-start gap-3 py-8 text-sm">
          {#if query.q !== ""}
            <p>{m.no_results_found()}</p>
          {:else if summary.state === "never"}
            <p>{m.integration_documents_empty_never_synced()}</p>
          {:else}
            <p>{m.integration_documents_empty_synced()}</p>
            <Button variant="link" class="h-auto p-0" onclick={() => (tab = "skipped")}>
              {m.integration_documents_empty_see_skipped()}
            </Button>
          {/if}
        </div>
      {/if}
    </Tabs.Content>

    <Tabs.Content value="skipped" class="flex flex-col gap-4">
      {#if skippedLoading}
        <div class="text-secondary flex items-center gap-2 text-sm" role="status">
          <IconLoadingSpinner size="sm" class="animate-spin" />
          <span>{m.loading()}</span>
        </div>
      {:else if skippedError || !skipped}
        <div
          class="text-negative-stronger bg-negative-dimmer flex flex-wrap items-center gap-3 rounded p-4 text-sm"
          role="alert"
        >
          <span>
            {m.integration_skipped_load_failed()}{#if skippedError}: {skippedError}{/if}
          </span>
          <Button variant="outline" size="sm" onclick={loadSkipped}>{m.retry()}</Button>
        </div>
      {:else if skipped.items.length === 0}
        <p class="text-secondary py-8 text-sm">{m.integration_skipped_empty()}</p>
      {:else}
        {#if skipped.synced_at}
          <p class="text-muted text-xs">
            {m.integration_skipped_synced_at({ time: formatDateTime(skipped.synced_at) })}
          </p>
        {/if}
        {#each skippedGroups as group, index (group.reason)}
          <section aria-labelledby="skipped-reason-{index}" class="text-sm">
            <h3 id="skipped-reason-{index}" class="text-warning-stronger font-medium">
              {m.integration_skipped_group_heading({
                reason: group.reason,
                count: group.files.length
              })}
            </h3>
            <ul class="mt-1 ml-4 list-disc space-y-0.5 break-all">
              <!-- The same file name recurs across folders, so the key needs the position. -->
              {#each group.files as file, fileIndex (`${fileIndex}:${file}`)}
                <li>{file}</li>
              {/each}
            </ul>
          </section>
        {/each}
        {#if skipped.truncated}
          <p class="text-muted text-sm italic">
            {skippedNotListed > 0
              ? m.skipped_and_n_more({ count: skippedNotListed })
              : m.skipped_list_truncated()}
          </p>
        {/if}
      {/if}
    </Tabs.Content>
  </Tabs.Root>
</div>
