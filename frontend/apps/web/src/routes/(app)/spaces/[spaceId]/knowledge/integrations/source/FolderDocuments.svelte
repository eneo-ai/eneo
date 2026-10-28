<script lang="ts">
  import { onDestroy, onMount, tick, untrack } from "svelte";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconLinkExternal } from "@eneo/icons/link-external";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import SortButton from "$lib/components/resource-table/SortButton.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage } from "$lib/core/errors";
  import { focusHandoff } from "$lib/core/focus/focusHandoff";
  import { formatDateTime, formatRelativeTime } from "$lib/core/formatting/dateTime";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import {
    DEFAULT_INTEGRATION_DOCUMENTS_QUERY,
    INTEGRATION_DOCUMENTS_QUERY_MAX_LENGTH,
    documentsPageRange,
    lastPageOffset,
    toggleDocumentsSort,
    type IntegrationDocumentSort,
    type IntegrationDocumentsPage,
    type IntegrationDocumentsQuery,
    type IntegrationSkippedDocuments
  } from "$lib/features/integrations/integrationDocuments";
  import { previewLinkLabel } from "$lib/features/integrations/IntegrationData";
  import SourceStateBadge from "$lib/features/integrations/components/SourceStateBadge.svelte";
  import { safeExternalUrl } from "$lib/features/integrations/externalUrl";
  import { itemState, itemWatchState, watchStateLabel } from "$lib/features/integrations/sources";
  import type { IntegrationSyncProgress } from "$lib/features/integrations/syncProgress";
  import BlobPreview from "$lib/features/knowledge/components/BlobPreview.svelte";
  import { describeSkipReason } from "$lib/features/integrations/skipReasons";
  import Check from "@lucide/svelte/icons/check";
  import LiveSyncFeed from "./LiveSyncFeed.svelte";
  import { m } from "$lib/paraglide/messages";
  import IntegrationActions from "../IntegrationActions.svelte";

  interface Props {
    knowledge: IntegrationKnowledge;
    space: { id: string };
    progress: Record<string, IntegrationSyncProgress>;
    /** Folders whose queued sync no worker has reported on yet. */
    queued?: ReadonlySet<string>;
    /** The files this item's latest sync skipped; null while unknown or not loadable. */
    skipped: IntegrationSkippedDocuments | null;
    problemsHref: string;
    /** Show the folder's own heading and actions; off when the source is this one item. */
    showHeader?: boolean;
    /** Show the folder's link and actions in its heading; off when the page header has them. */
    showControls?: boolean;
  }

  let {
    knowledge,
    space,
    progress,
    queued,
    skipped,
    problemsHref,
    showHeader = true,
    showControls = true
  }: Props = $props();

  const eneo = getEneo();
  const SEARCH_DEBOUNCE_MS = 300;

  // The query the rows and the sort headers show; a failed request leaves it as it was.
  let query = $state<IntegrationDocumentsQuery>({ ...DEFAULT_INTEGRATION_DOCUMENTS_QUERY });
  let requestedQuery: IntegrationDocumentsQuery | null = null;
  let documents = $state<IntegrationDocumentsPage | null>(null);
  let loading = $state(false);
  // A reload after a sync replaces the rows without a word; the page already says the sync ended.
  let quietLoad = $state(false);
  let rangeAnnouncement = $state("");
  let error = $state<string | null>(null);
  let searchText = $state("");
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  let loadGeneration = 0;
  let previousButton = $state<HTMLElement | null>(null);
  let nextButton = $state<HTMLElement | null>(null);

  let folderState = $derived(itemState(knowledge, progress, queued));
  let watchState = $derived(itemWatchState(knowledge));
  let knowledgeUrl = $derived(safeExternalUrl(knowledge.url));
  let view = $state<"searchable" | "skipped">("searchable");
  let skippedTotal = $derived(skipped?.total ?? 0);
  let skippedNotListed = $derived(skipped ? Math.max(0, skipped.total - skipped.items.length) : 0);
  let range = $derived(documents ? documentsPageRange(documents) : null);
  let hasPrevious = $derived((documents?.offset ?? 0) > 0);
  let hasNext = $derived(
    documents !== null && documents.offset + documents.items.length < documents.total_count
  );
  let sourceLinkLabel = $derived(previewLinkLabel(knowledge.integration_type));

  const sortColumns: { id: IntegrationDocumentSort; label: () => string }[] = [
    { id: "name", label: () => m.name() },
    { id: "path", label: () => m.integration_documents_path() },
    { id: "size", label: () => m.size() },
    { id: "updated_at", label: () => m.integration_documents_updated() }
  ];

  const ariaSort = { asc: "ascending", desc: "descending" } as const;

  /** `user` speaks the new range; `open` and `quiet` don't, and `quiet` shows no loading line either. */
  async function loadDocuments(
    next: IntegrationDocumentsQuery,
    how: "open" | "user" | "quiet" = "user"
  ) {
    const generation = ++loadGeneration;
    requestedQuery = next;
    // A quiet reload that supersedes a load someone asked for keeps its loading line.
    quietLoad = how === "quiet" && !(loading && !quietLoad);
    loading = true;
    error = null;
    try {
      const page = await eneo.integrations.knowledge.listDocuments({
        knowledge,
        space,
        ...next
      });
      if (generation !== loadGeneration) return;
      query = next;
      // Documents deleted while paging can leave this offset past the end.
      const lastOffset = lastPageOffset(page, next.limit);
      if (page.items.length === 0 && next.offset > lastOffset) {
        return loadDocuments({ ...next, offset: lastOffset }, how);
      }
      documents = page;
      if (how === "user") {
        const text =
          page.items.length > 0
            ? m.integration_documents_showing_range(documentsPageRange(page))
            : next.q !== ""
              ? m.no_results_found()
              : "";
        // Cleared first, so a result that reads the same as the last one is spoken again.
        rangeAnnouncement = "";
        await tick();
        if (generation === loadGeneration) rangeAnnouncement = text;
      }
    } catch (err) {
      if (generation !== loadGeneration) return;
      error = getErrorMessage(err);
    } finally {
      if (generation === loadGeneration) loading = false;
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
    const offset = Math.max(0, (documents?.offset ?? 0) + direction * query.limit);
    await loadDocuments({ ...query, offset });
    await handoff.to(other);
  }

  onMount(() => {
    void loadDocuments(query, "open");
  });

  // A finished sync, from this user or from a change in SharePoint, moves the
  // timestamps; reload so the table shows what the sync wrote.
  let syncedSignature = $derived(
    `${knowledge.metadata?.last_synced_at ?? ""}|${knowledge.metadata?.document_count ?? 0}`
  );
  let seenSignature = untrack(() => syncedSignature);
  $effect(() => {
    const signature = syncedSignature;
    if (signature === seenSignature) return;
    seenSignature = signature;
    // A search or sort still loading is what the reader asked for; reload that, not the last shown.
    untrack(() => void loadDocuments(requestedQuery ?? query, "quiet"));
  });

  onDestroy(() => clearTimeout(searchTimer));
</script>

<section class="flex min-w-0 flex-col gap-3" aria-labelledby="folder-documents-{knowledge.id}">
  {#if showHeader}
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="flex min-w-0 flex-col gap-1">
        <h2
          id="folder-documents-{knowledge.id}"
          tabindex="-1"
          data-content-heading
          class="focus-visible:ring-stronger truncate rounded text-base font-semibold focus-visible:ring-2 focus-visible:outline-none"
        >
          {knowledge.name}
          {#if knowledge.original_name && knowledge.original_name !== knowledge.name}
            <span class="text-secondary text-sm font-normal">({knowledge.original_name})</span>
          {/if}
        </h2>
        <div class="text-secondary flex flex-wrap items-center gap-2 text-xs">
          <SourceStateBadge state={folderState} />
          {#if knowledge.metadata?.last_synced_at}
            <span>
              {m.integration_source_last_up_to_date_at({
                time: formatRelativeTime(knowledge.metadata.last_synced_at)
              })}
            </span>
          {:else if knowledge.metadata?.last_sync_attempted_at}
            <span>
              {m.integration_source_last_attempt_at({
                time: formatRelativeTime(knowledge.metadata.last_sync_attempted_at)
              })}
            </span>
          {/if}
          {#if knowledge.integration_type === "sharepoint"}
            <span class={watchState === "expired" ? "text-warning-stronger" : undefined}>
              {m.integration_source_watch_state_line({ state: watchStateLabel(watchState) })}
            </span>
          {/if}
          {#if knowledge.folder_path}
            <span class="break-all">{knowledge.folder_path}</span>
          {/if}
        </div>
      </div>
      {#if showControls}
        <div class="flex items-center gap-1">
          {#if knowledgeUrl}
            <Button
              variant="outline"
              size="sm"
              href={knowledgeUrl}
              target="_blank"
              rel="noopener noreferrer"
            >
              {sourceLinkLabel}
              <IconLinkExternal size="sm" data-icon="inline-end" />
            </Button>
          {/if}
          <IntegrationActions
            knowledgeItem={knowledge}
            syncActive={folderState === "syncing" || folderState === "queued"}
          />
        </div>
      {/if}
    </div>
  {:else}
    <h2 id="folder-documents-{knowledge.id}" tabindex="-1" data-content-heading class="sr-only">
      {m.documents()}
    </h2>
  {/if}

  {#if progress[knowledge.id]}
    <LiveSyncFeed progress={progress[knowledge.id]} />
  {/if}

  <div
    role="group"
    aria-label={m.integration_source_document_views()}
    class="flex flex-wrap items-center gap-2"
  >
    <Button
      size="sm"
      variant={view === "searchable" ? "default" : "outline"}
      aria-pressed={view === "searchable"}
      onclick={() => (view = "searchable")}
    >
      {m.integration_source_view_searchable({ count: knowledge.metadata?.document_count ?? 0 })}
    </Button>
    <Button
      size="sm"
      variant={view === "skipped" ? "default" : "outline"}
      aria-pressed={view === "skipped"}
      disabled={skipped === null}
      onclick={() => (view = "skipped")}
    >
      {m.integration_source_view_unreadable({ count: skippedTotal })}
    </Button>
  </div>

  {#if view === "skipped" && skipped}
    {#if skipped.items.length === 0}
      <p class="text-secondary py-8 text-sm">{m.integration_source_nothing_skipped()}</p>
    {:else}
      <Table.Root aria-label={m.integration_source_skipped_table_label({ name: knowledge.name })}>
        <Table.Header>
          <Table.Row>
            <Table.Head>{m.name()}</Table.Head>
            <Table.Head>{m.integration_source_skip_reason()}</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          <!-- The same file name recurs across folders, so the key needs the position. -->
          {#each skipped.items as file, index (`${index}:${file.file}`)}
            <Table.Row>
              <Table.Cell class="max-w-[28rem] font-medium break-all whitespace-normal"
                >{file.file}</Table.Cell
              >
              <Table.Cell class="text-warning-stronger whitespace-normal">
                {describeSkipReason(file)}
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
      <p class="text-secondary flex flex-wrap gap-x-3 text-sm">
        {#if skippedNotListed > 0}
          <span class="italic">{m.skipped_and_n_more({ count: skippedNotListed })}</span>
        {/if}
        <!-- eslint-disable svelte/no-navigation-without-resolve -- href comes from the caller -->
        <a
          href={problemsHref}
          class="text-accent-default focus-visible:ring-stronger rounded font-medium hover:underline focus-visible:ring-2 focus-visible:outline-none"
        >
          {m.integration_source_show_in_problems()}
        </a>
        <!-- eslint-enable svelte/no-navigation-without-resolve -->
      </p>
    {/if}
  {:else}
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
        <Button variant="outline" size="sm" onclick={() => loadDocuments(requestedQuery ?? query)}>
          {m.retry()}
        </Button>
      </div>
    {/if}

    <p class="sr-only" role="status">{rangeAnnouncement}</p>

    {#if loading && !quietLoad}
      <div class="text-secondary flex items-center gap-2 text-sm" role="status">
        <IconLoadingSpinner size="sm" class="motion-safe:animate-spin" />
        <span>{m.integration_documents_loading()}</span>
      </div>
    {/if}

    {#if documents && documents.items.length > 0 && range}
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
              <Table.Head>{m.status()}</Table.Head>
              <Table.Head class="w-[1%]"><span class="sr-only">{m.actions()}</span></Table.Head>
            </Table.Row>
          </Table.Header>
          <Table.Body>
            {#each documents.items as document (document.id)}
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
                <Table.Cell class="tabular-nums">{formatDateTime(document.updated_at)}</Table.Cell>
                <Table.Cell>
                  <span class="text-positive-stronger inline-flex items-center gap-1.5 text-sm">
                    <Check class="size-4" aria-hidden="true" />
                    {m.integration_source_doc_searchable()}
                  </span>
                </Table.Cell>
                <Table.Cell>
                  {#if safeExternalUrl(document.url)}
                    <Button
                      href={safeExternalUrl(document.url)}
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
        <p class="text-secondary">
          {m.integration_documents_showing_range(range)}
          <span class="text-muted">
            · {m.integration_documents_total_size({ size: formatBytes(documents.total_size) })}
          </span>
        </p>
        <!-- disabled only for a page that does not exist; while loading the buttons stay
             focusable, since a focused button that turns disabled drops focus to the body. -->
        <div class="flex gap-2">
          <Button
            variant="outline"
            size="sm"
            bind:ref={previousButton}
            disabled={!hasPrevious}
            aria-disabled={loading}
            class={loading ? "pointer-events-none opacity-50" : undefined}
            onclick={() => goToPage(-1)}
          >
            {m.previous()}
          </Button>
          <Button
            variant="outline"
            size="sm"
            bind:ref={nextButton}
            disabled={!hasNext}
            aria-disabled={loading}
            class={loading ? "pointer-events-none opacity-50" : undefined}
            onclick={() => goToPage(1)}
          >
            {m.next()}
          </Button>
        </div>
      </div>
    {:else if documents && !loading && !error}
      <div class="text-secondary py-8 text-sm">
        {#if query.q !== ""}
          <p>{m.no_results_found()}</p>
        {:else if folderState === "syncing"}
          <p>{m.integration_source_folder_empty_syncing()}</p>
        {:else if folderState === "never"}
          <p>{m.integration_documents_empty_never_synced()}</p>
        {:else}
          <p>{m.integration_documents_empty_synced()}</p>
        {/if}
      </div>
    {/if}
  {/if}
</section>
