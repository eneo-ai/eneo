<script lang="ts">
  import { onDestroy, onMount, untrack } from "svelte";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconLinkExternal } from "@eneo/icons/link-external";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import SortButton from "$lib/components/resource-table/SortButton.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage } from "$lib/core/errors";
  import { formatDateTime, formatRelativeTime } from "$lib/core/formatting/dateTime";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import {
    DEFAULT_INTEGRATION_DOCUMENTS_QUERY,
    documentsPageRange,
    lastPageOffset,
    toggleDocumentsSort,
    type IntegrationDocumentSort,
    type IntegrationDocumentsPage,
    type IntegrationDocumentsQuery
  } from "$lib/features/integrations/integrationDocuments";
  import { previewLinkLabel } from "$lib/features/integrations/IntegrationData";
  import SourceStateBadge from "$lib/features/integrations/components/SourceStateBadge.svelte";
  import { itemState } from "$lib/features/integrations/sources";
  import type { IntegrationSyncProgress } from "$lib/features/integrations/syncProgress";
  import BlobPreview from "$lib/features/knowledge/components/BlobPreview.svelte";
  import SourceMetadataList from "$lib/features/knowledge/components/SourceMetadataList.svelte";
  import { hasSourceMetadata } from "$lib/features/knowledge/sourceMetadata";
  import { m } from "$lib/paraglide/messages";
  import IntegrationActions from "../IntegrationActions.svelte";

  interface Props {
    knowledge: IntegrationKnowledge;
    space: { id: string };
    progress: Record<string, IntegrationSyncProgress>;
    /** Files of this item the latest sync skipped; null while unknown. */
    skippedCount: number | null;
    problemsHref: string;
    /** Show the folder's own heading and actions; off when the source is this one item. */
    showHeader?: boolean;
  }

  let {
    knowledge,
    space,
    progress,
    skippedCount,
    problemsHref,
    showHeader = true
  }: Props = $props();

  const eneo = getEneo();
  const SEARCH_DEBOUNCE_MS = 300;

  let query = $state<IntegrationDocumentsQuery>({ ...DEFAULT_INTEGRATION_DOCUMENTS_QUERY });
  let documents = $state<IntegrationDocumentsPage | null>(null);
  let loading = $state(false);
  let error = $state<string | null>(null);
  let searchText = $state("");
  let searchTimer: ReturnType<typeof setTimeout> | undefined;
  let loadGeneration = 0;

  let folderState = $derived(itemState(knowledge, progress));
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

  async function loadDocuments(next: IntegrationDocumentsQuery) {
    const generation = ++loadGeneration;
    query = next;
    loading = true;
    error = null;
    try {
      const page = (await eneo.integrations.knowledge.listDocuments({
        knowledge,
        space,
        ...next
      })) as IntegrationDocumentsPage;
      if (generation !== loadGeneration) return;
      // Documents deleted while paging can leave this offset past the end.
      const lastOffset = lastPageOffset(page, next.limit);
      if (page.items.length === 0 && next.offset > lastOffset) {
        return loadDocuments({ ...next, offset: lastOffset });
      }
      documents = page;
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

  function goToPage(direction: -1 | 1) {
    const offset = Math.max(0, (documents?.offset ?? 0) + direction * query.limit);
    void loadDocuments({ ...query, offset });
  }

  onMount(() => {
    void loadDocuments(query);
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
    untrack(() => void loadDocuments(query));
  });

  onDestroy(() => clearTimeout(searchTimer));
</script>

<section class="flex min-w-0 flex-col gap-3" aria-labelledby="folder-documents-{knowledge.id}">
  {#if showHeader}
    <div class="flex flex-wrap items-start justify-between gap-3">
      <div class="flex min-w-0 flex-col gap-1">
        <h2 id="folder-documents-{knowledge.id}" class="truncate text-base font-semibold">
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
          {#if knowledge.folder_path}
            <span class="break-all">{knowledge.folder_path}</span>
          {/if}
        </div>
      </div>
      <div class="flex items-center gap-1">
        {#if knowledge.url}
          <Button
            variant="outline"
            size="sm"
            href={knowledge.url}
            target="_blank"
            rel="noopener noreferrer"
          >
            {sourceLinkLabel}
            <IconLinkExternal size="sm" data-icon="inline-end" />
          </Button>
        {/if}
        <IntegrationActions knowledgeItem={knowledge} />
      </div>
    </div>
  {:else}
    <h2 id="folder-documents-{knowledge.id}" class="sr-only">{m.documents()}</h2>
  {/if}

  {#if skippedCount !== null && skippedCount > 0}
    <p class="text-secondary text-sm">
      {skippedCount === 1
        ? m.integration_source_folder_skipped_one()
        : m.integration_source_folder_skipped_other({ count: skippedCount })}
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

  <Input
    type="search"
    bind:value={searchText}
    oninput={onSearchInput}
    aria-label={m.integration_documents_search_label()}
    placeholder={m.integration_documents_search_placeholder()}
    class="max-w-md"
  />

  {#if error}
    <div
      class="text-negative-stronger bg-negative-dimmer flex flex-wrap items-center gap-3 rounded p-4 text-sm"
      role="alert"
    >
      <span>{m.integration_documents_load_failed()}: {error}</span>
      <Button variant="outline" size="sm" onclick={() => loadDocuments(query)}>
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
            <Table.Head>{m.integration_documents_properties()}</Table.Head>
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
                {#if document.url}
                  <Button
                    href={document.url}
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
        <Button
          variant="outline"
          size="sm"
          disabled={!hasPrevious || loading}
          onclick={() => goToPage(-1)}
        >
          {m.previous()}
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={!hasNext || loading}
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
</section>
