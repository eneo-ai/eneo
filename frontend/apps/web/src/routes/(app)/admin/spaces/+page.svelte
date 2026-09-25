<!--
  Admin → Ytor: every shared space in the organisation, what needs attention,
  and the administrator's own relation to each space. The whole list arrives
  at once; search, filters, sorting and paging run here and live in the URL.
-->
<script lang="ts">
  import { ExternalLink, RotateCw, TriangleAlert } from "@lucide/svelte";
  import { tick, untrack } from "svelte";
  import { invalidate, replaceState } from "$app/navigation";
  import { page } from "$app/state";
  import { Page } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import { docsUrl } from "$lib/core/docs";
  import { intlLocale } from "$lib/core/formatting/dateTime";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import SpacesAttention from "./SpacesAttention.svelte";
  import SpacesFilters from "./SpacesFilters.svelte";
  import SpacesTable from "./SpacesTable.svelte";
  import {
    DEFAULT_QUERY,
    PAGE_SIZE,
    clampPage,
    filterSpaces,
    isFiltered,
    isMember,
    membershipCounts,
    nextSort,
    pageCount,
    readSpaceListQuery,
    sortSpaces,
    spaceListQueryString,
    type SortColumn,
    type SpaceListQuery
  } from "./space-list-query";

  let { data } = $props();

  // Announcements wait until typing pauses, so a screen reader is not read every keystroke.
  const SETTLE_MS = 250;

  const locale = intlLocale();
  const number = new Intl.NumberFormat(locale);
  const collator = new Intl.Collator(locale);

  let query = $state<SpaceListQuery>(untrack(() => readSpaceListQuery(page.url)));
  let allHeading = $state<HTMLHeadingElement | null>(null);
  let searchInput = $state<HTMLInputElement | null>(null);
  let retrying = $state(false);

  const items = $derived(data.list?.items ?? []);
  const requests = $derived(data.list?.widget_requests ?? []);
  const matching = $derived(
    sortSpaces(filterSpaces(items, query), query.sort, query.dir, collator)
  );
  const pages = $derived(pageCount(matching.length));
  const currentPage = $derived(clampPage(query.page, matching.length));
  const visible = $derived(matching.slice((currentPage - 1) * PAGE_SIZE, currentPage * PAGE_SIZE));
  const counts = $derived(membershipCounts(items, query));
  const memberOf = $derived(items.filter(isMember).length);

  const results = $derived(
    items.length === 1
      ? m.admin_spaces_results_one({ shown: number.format(matching.length) })
      : m.admin_spaces_results({
          shown: number.format(matching.length),
          total: number.format(items.length)
        })
  );
  let announced = $state(untrack(() => results));
  $effect(() => {
    const text = results;
    const timer = setTimeout(() => (announced = text), SETTLE_MS);
    return () => clearTimeout(timer);
  });

  // The URL follows the list without a reload or a new history entry. The
  // router's URL does not change with replaceState, so compare with the last write.
  let written = untrack(() => spaceListQueryString(query, { page: query.page }));
  $effect(() => {
    const search = spaceListQueryString(query, { page: currentPage });
    if (search === written) return;
    const timer = setTimeout(() => {
      written = search;
      // Same page, only the query changes: nothing to resolve.
      // eslint-disable-next-line svelte/no-navigation-without-resolve
      replaceState(`${page.url.pathname}${search}${page.url.hash}`, page.state);
    }, SETTLE_MS);
    return () => clearTimeout(timer);
  });

  function update(change: Partial<SpaceListQuery>) {
    query = { ...query, page: 1, ...change };
  }

  async function focusList() {
    await tick();
    allHeading?.focus();
  }

  function sortLabel(column: SortColumn) {
    switch (column) {
      case "name":
        return m.admin_spaces_col_space();
      case "members":
        return m.members();
      case "activity":
        return m.admin_spaces_col_last_active();
      default:
        return column satisfies never;
    }
  }

  async function clearFilters() {
    update({ q: DEFAULT_QUERY.q, membership: DEFAULT_QUERY.membership, show: DEFAULT_QUERY.show });
    // The button goes away with the filters; the search field is where they start again.
    await tick();
    searchInput?.focus();
  }

  async function retry() {
    retrying = true;
    try {
      await invalidate("admin:spaces");
    } finally {
      retrying = false;
    }
  }
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.admin_spaces_nav()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.admin_spaces_nav()} tour="admin-spaces"></Page.Title>
    {#if data.list && items.length > 0}
      <Page.Flex>
        <span class="text-secondary text-sm">
          {items.length === 1
            ? m.admin_spaces_summary_one({ memberOf: number.format(memberOf) })
            : m.admin_spaces_summary({
                count: number.format(items.length),
                memberOf: number.format(memberOf)
              })}
        </span>
      </Page.Flex>
    {/if}
  </Page.Header>
  <Page.Main>
    <div
      class="mx-auto flex w-full max-w-[1400px] flex-col gap-8 p-4"
      aria-busy={retrying || undefined}
    >
      <p class="text-secondary max-w-[75ch]">
        {m.admin_spaces_intro()}
        <!-- eslint-disable svelte/no-navigation-without-resolve -- external docs site -->
        <a
          href={docsUrl("guides/space-oversight", getLocale())}
          target="_blank"
          rel="noreferrer"
          class="text-accent-stronger inline-flex items-center gap-1 underline underline-offset-2"
        >
          {m.admin_spaces_learn_more()}
          <ExternalLink class="size-3.5" aria-hidden="true" />
        </a>
        <!-- eslint-enable svelte/no-navigation-without-resolve -->
      </p>

      {#if !data.list}
        <div
          role="alert"
          class="bg-negative-dimmer text-negative-stronger flex flex-col gap-3 rounded-lg p-4 @2xl:flex-row @2xl:items-center"
        >
          <p class="flex flex-1 items-start gap-2">
            <TriangleAlert class="mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {m.admin_spaces_load_failed()}
          </p>
          <Button
            variant="outline"
            class={["w-fit max-md:min-h-12", retrying && "pointer-events-none opacity-50"]}
            aria-disabled={retrying}
            onclick={retry}
          >
            <RotateCw aria-hidden="true" data-icon="inline-start" />
            {m.retry()}
          </Button>
        </div>
      {:else}
        <SpacesAttention
          {items}
          {requests}
          onShowNoAdmin={() => {
            update({ show: "no_admin" });
            void focusList();
          }}
        />

        <section aria-labelledby="spaces-all-title" class="flex flex-col gap-4">
          <h2
            id="spaces-all-title"
            bind:this={allHeading}
            tabindex="-1"
            class="text-lg font-semibold outline-none"
          >
            {m.admin_spaces_all_title()}
          </h2>

          {#if items.length === 0}
            <p class="text-secondary">{m.admin_spaces_empty_tenant()}</p>
          {:else}
            <SpacesFilters
              {query}
              {counts}
              filtered={isFiltered(query)}
              onChange={update}
              onClear={clearFilters}
              bind:searchInput
            />

            <p role="status" class="text-secondary text-sm">{announced}</p>

            <SpacesTable
              items={visible}
              {query}
              securityEnabled={data.securityEnabled}
              caption={m.admin_spaces_table_caption({ column: sortLabel(query.sort) })}
              onSort={(column) => update(nextSort(query, column))}
              onClearFilters={clearFilters}
            />

            {#if pages > 1}
              <nav
                aria-label={m.admin_spaces_pagination_label()}
                class="flex flex-wrap items-center gap-3"
              >
                <Button
                  variant="outline"
                  class="max-md:min-h-12"
                  disabled={currentPage <= 1}
                  onclick={() => {
                    update({ page: currentPage - 1 });
                    void focusList();
                  }}
                >
                  {m.previous()}
                </Button>
                <span class="text-sm tabular-nums">
                  {m.admin_spaces_page_of({
                    page: number.format(currentPage),
                    pages: number.format(pages)
                  })}
                </span>
                <Button
                  variant="outline"
                  class="max-md:min-h-12"
                  disabled={currentPage >= pages}
                  onclick={() => {
                    update({ page: currentPage + 1 });
                    void focusList();
                  }}
                >
                  {m.next()}
                </Button>
              </nav>
            {/if}
          {/if}

          <p class="text-secondary max-w-[75ch] text-sm">{m.admin_spaces_footer_note()}</p>
        </section>
      {/if}
    </div>
  </Page.Main>
</Page.Root>
