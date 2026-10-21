<script lang="ts">
  import { untrack } from "svelte";
  import { page } from "$app/state";
  import { replaceState } from "$app/navigation";
  import type { WebsiteInfoBlobPage } from "@eneo/eneo-js";
  import { getEneo } from "$lib/core/Eneo";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import BlobPreview from "$lib/features/knowledge/components/BlobPreview.svelte";
  import CrawlLoadError from "$lib/features/knowledge/CrawlLoadError.svelte";
  import { m } from "$lib/paraglide/messages";
  import WebsiteFolderNav from "./WebsiteFolderNav.svelte";
  import type { WebsiteContentFilters } from "./websiteContentFilters";

  let {
    websiteId,
    initialPage,
    revision,
    prefix = $bindable(""),
    query = $bindable(""),
    initialContent = $bindable(null)
  }: {
    websiteId: string;
    /** The whole website's first page. */
    initialPage: WebsiteInfoBlobPage;
    /** The crawl whose indexed snapshot is listed; a new snapshot reloads the selection. */
    revision: string | undefined;
    /** The selected URL directory. The page owns it, so it outlives a tab switch. */
    prefix?: string;
    /** The applied title and URL search. */
    query?: string;
    /** The server's page for the URL's filters. Cleared once shown: a later mount fetches its own. */
    initialContent?: (WebsiteContentFilters & { page: WebsiteInfoBlobPage }) | null;
  } = $props();
  const eneo = getEneo();
  let documents = $state<WebsiteInfoBlobPage | null>(null);
  let searchText = $state("");
  let loading = $state(false);
  let failed = $state(false);
  let retryCursor: string | null = null;
  let generation = 0;
  let listedSelection: string | null = null;
  let searchTimer: ReturnType<typeof setTimeout> | undefined;

  function hrefFor(path: string | null) {
    const url = new URL(page.url);
    url.searchParams.set("tab", "blobs");
    if (path) url.searchParams.set("prefix", path);
    else url.searchParams.delete("prefix");
    if (query) url.searchParams.set("q", query);
    else url.searchParams.delete("q");
    return `${url.pathname}${url.search}`;
  }

  function syncUrl() {
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- current route with content filters
    replaceState(hrefFor(prefix), { ...page.state, tab: "blobs" });
  }

  async function load(cursor: string | null = null) {
    const request = ++generation;
    retryCursor = cursor;
    loading = true;
    failed = false;
    try {
      const result = await eneo.websites.indexedBlobs.listPage({
        id: websiteId,
        limit: 100,
        cursor,
        ...(prefix ? { prefix } : {}),
        ...(query ? { q: query } : {})
      });
      if (request !== generation) return;
      const known = new Set(cursor ? documents?.items.map((item) => item.id) : []);
      documents = {
        ...result,
        items: [
          ...(cursor ? (documents?.items ?? []) : []),
          ...result.items.filter((item) => !known.has(item.id))
        ]
      };
    } catch {
      if (request === generation) failed = true;
    } finally {
      if (request === generation) loading = false;
    }
  }

  // The website, filters and crawl snapshot decide what is listed. New filters
  // clear the list; a new snapshot of the same selection keeps it until reloaded.
  // A reload of the page data within one snapshot changes nothing here.
  $effect(() => {
    const selection = `${websiteId}\n${prefix}\n${query}`;
    void revision;
    untrack(() => {
      const sameSelection = selection === listedSelection;
      listedSelection = selection;
      if (searchText.trim() !== query) searchText = query;
      generation += 1;
      if (!sameSelection && initialContent?.prefix === prefix && initialContent.q === query) {
        documents = initialContent.page;
        initialContent = null;
        loading = false;
        failed = false;
      } else if (prefix || query) {
        if (!sameSelection) documents = null;
        void load();
      } else {
        documents = initialPage;
        loading = false;
        failed = false;
      }
    });
    return () => {
      generation += 1;
    };
  });

  function selectPrefix(path: string | null) {
    const next = path ?? "";
    if (next === prefix) return;
    prefix = next;
    syncUrl();
  }

  function search() {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => {
      const next = searchText.trim();
      if (next === query) return;
      query = next;
      syncUrl();
    }, 300);
  }

  function contentCount(shown: number, total: number) {
    return total === 1
      ? m.website_source_content_count_one({ shown, total })
      : m.website_source_content_count_other({ shown, total });
  }

  $effect(() => () => {
    clearTimeout(searchTimer);
    generation += 1;
  });
</script>

<div class="grid min-w-0 gap-6 py-5 pr-4 lg:grid-cols-[15rem_minmax(0,1fr)]">
  <aside
    class="border-default max-h-72 overflow-y-auto border-b pb-4 lg:max-h-[calc(100vh-18rem)] lg:border-r lg:border-b-0 lg:pr-4"
  >
    <WebsiteFolderNav
      {websiteId}
      {revision}
      total={initialPage.total_count}
      selectedPrefix={prefix}
      {hrefFor}
      onselect={selectPrefix}
    />
  </aside>
  <section class="flex min-w-0 flex-col gap-4" aria-label={m.indexed_content()} aria-busy={loading}>
    <div>
      <h2 class="text-base font-semibold break-all">{prefix || m.website_source_all_content()}</h2>
      <p class="text-secondary mt-1 text-sm">{m.website_source_content_hint()}</p>
    </div>
    <Input
      type="search"
      maxlength={200}
      bind:value={searchText}
      oninput={search}
      aria-label={m.website_source_search()}
      placeholder={m.website_source_search()}
    />
    {#if failed}
      <CrawlLoadError
        message={m.website_source_content_load_failed()}
        {loading}
        onretry={() => load(retryCursor)}
      />
    {/if}
    {#if documents && documents.items.length > 0}
      <Table.Root>
        <Table.Header
          ><Table.Row>
            <Table.Head>{m.name()}</Table.Head><Table.Head>{m.created()}</Table.Head>
            <Table.Head class="text-right">{m.size()}</Table.Head>
          </Table.Row></Table.Header
        >
        <Table.Body>
          {#each documents.items as blob (blob.id)}
            <Table.Row>
              <Table.Cell class="max-w-0 whitespace-normal">
                <BlobPreview {blob} let:showBlob>
                  <button
                    type="button"
                    onclick={showBlob}
                    class="text-primary focus-visible:ring-stronger max-w-full rounded text-left font-medium break-words hover:underline focus-visible:ring-2 focus-visible:outline-none"
                  >
                    {blob.metadata.title || blob.metadata.url || m.untitled()}
                  </button>
                </BlobPreview>
                <p
                  class="text-secondary mt-1 truncate text-xs"
                  title={blob.metadata.url ?? undefined}
                >
                  {blob.metadata.url}
                </p>
              </Table.Cell>
              <Table.Cell class="text-secondary w-40 text-xs"
                >{formatDateTime(blob.created_at)}</Table.Cell
              >
              <Table.Cell class="text-secondary w-24 text-right text-xs tabular-nums"
                >{formatBytes(blob.metadata.size)}</Table.Cell
              >
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    {:else if documents && !loading}
      <p class="text-secondary py-8 text-sm">
        {query || prefix ? m.no_results_found() : m.website_no_indexed_content()}
      </p>
    {/if}
    <div role="status" class="text-secondary text-sm">
      {#if loading}{m.loading()}
      {:else if documents}{contentCount(documents.items.length, documents.total_count)}{/if}
    </div>
    {#if documents?.next_cursor && !failed}
      <div>
        <Button
          variant="outline"
          disabled={loading}
          onclick={() => load(documents?.next_cursor ?? null)}
        >
          {loading
            ? m.loading_more()
            : m.website_indexed_content_load_more({
                current: documents.items.length,
                total: documents.total_count
              })}
        </Button>
      </div>
    {/if}
  </section>
</div>
