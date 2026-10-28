<script lang="ts">
  import { onMount, tick, untrack } from "svelte";
  import { writable } from "svelte/store";
  import type { CrawlRun } from "@eneo/eneo-js";
  import Info from "@lucide/svelte/icons/info";
  import LoaderCircle from "@lucide/svelte/icons/loader-circle";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import { afterNavigate } from "$app/navigation";
  import { page } from "$app/state";
  import { Page } from "$lib/components/layout";
  import { selectPageTab } from "$lib/components/layout/Page/ctx";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { PAGINATION } from "$lib/core/constants";
  import { toastError } from "$lib/core/errors";
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import { formatWebsiteName } from "$lib/core/formatting/formatWebsiteName.js";
  import CrawlRunDetailsContent from "$lib/features/knowledge/CrawlRunDetailsContent.svelte";
  import CrawlRunStatus from "$lib/features/knowledge/CrawlRunStatus.svelte";
  import SourceStat from "$lib/features/knowledge/components/SourceStat.svelte";
  import SourceStats from "$lib/features/knowledge/components/SourceStats.svelte";
  import {
    hasCrawlIssues,
    isActiveCrawlRun,
    isCompletedWithMissingResources
  } from "$lib/features/knowledge/crawlRunState";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import CrawlCreateRun from "./CrawlCreateRun.svelte";
  import CrawlLimitations from "./CrawlLimitations.svelte";
  import CrawlRunActivity from "./CrawlRunActivity.svelte";
  import WebsiteContent from "./WebsiteContent.svelte";
  import { readContentFilters } from "./websiteContentFilters";
  import { mergeLatestCrawlRun, pollWebsiteDetail } from "./websiteDetailPolling";
  import type { PageData } from "./$types";

  let { data }: { data: PageData } = $props();

  const eneo = getEneo();
  const {
    state: { currentSpace }
  } = getSpacesManager();
  const tabs = writable<string>();

  let startDialogOpen = $state(false);
  // null follows the latest completed crawl. A chosen older run is kept as an object:
  // replacing the history with its first page must not swap the run shown.
  let selectedProblemRun = $state.raw<CrawlRun | null>(null);
  let problemHeading = $state<HTMLHeadingElement | undefined>();

  // Server data seeds the local copies; the effects below follow later server data.
  // svelte-ignore state_referenced_locally
  let crawlRuns = $state.raw(data.crawlRuns);
  // svelte-ignore state_referenced_locally
  let nextCrawlRunCursor = $state.raw(data.nextCrawlRunCursor);
  // svelte-ignore state_referenced_locally
  let totalCrawlRunCount = $state(data.totalCrawlRunCount);
  // svelte-ignore state_referenced_locally
  let infoBlobPage = $state.raw(data.infoBlobPage);
  // svelte-ignore state_referenced_locally
  let initialContent = $state.raw(data.initialContent ?? null);
  // The crawl whose indexed snapshot Content shows; only a new one reloads it.
  let contentRunId = $state(
    untrack(() => data.crawlRuns.find((run) => !isActiveCrawlRun(run))?.id)
  );
  // Shallow URL updates never reach page.url, and invalidate() reloads against the
  // last navigation's URL. The page therefore owns the selection; navigations replace it.
  let contentFilters = $state(readContentFilters(page.url.searchParams));
  afterNavigate(({ to }) => {
    if (to) contentFilters = readContentFilters(to.url.searchParams);
  });
  let loadingMoreCrawlRuns = $state(false);
  // Request bookkeeping, never rendered.
  let crawlRunPageGeneration = 0;
  let pollingCrawlRuns = false;
  let historyRunId = untrack(() => data.crawlRuns[0]?.id);
  let problemWebsiteId = untrack(() => data.website.id);
  let seededContent = untrack(() => data.initialContent ?? null);

  // Server data changes with the route and with invalidate() after starting or
  // stopping a crawl; polling results are kept otherwise.
  $effect(() => {
    const serverRuns = data.crawlRuns;
    const serverCursor = data.nextCrawlRunCursor;
    const serverTotal = data.totalCrawlRunCount;
    const websiteId = data.website.id;
    untrack(() => {
      crawlRuns = serverRuns;
      nextCrawlRunCursor = serverCursor;
      totalCrawlRunCount = serverTotal;
      crawlRunPageGeneration += 1;
      loadingMoreCrawlRuns = false;
      historyRunId = serverRuns[0]?.id;
      if (websiteId !== problemWebsiteId) {
        problemWebsiteId = websiteId;
        selectedProblemRun = null;
      }
    });
  });
  $effect(() => {
    const serverPage = data.infoBlobPage;
    const serverContent = data.initialContent ?? null;
    const serverRuns = data.crawlRuns;
    untrack(() => {
      infoBlobPage = serverPage;
      // Content clears it once shown; only a new server load provides another.
      if (serverContent !== seededContent) {
        seededContent = serverContent;
        initialContent = serverContent;
      }
      contentRunId = serverRuns.find((run) => !isActiveCrawlRun(run))?.id;
    });
  });

  const completedRuns = $derived(crawlRuns.filter((run) => !isActiveCrawlRun(run)));
  const latestCompletedRun = $derived<CrawlRun | undefined>(completedRuns[0]);
  const problemRun = $derived(
    selectedProblemRun
      ? (completedRuns.find((run) => run.id === selectedProblemRun?.id) ?? selectedProblemRun)
      : latestCompletedRun
  );
  const problemRunChoices = $derived(
    problemRun && !completedRuns.some((run) => run.id === problemRun.id)
      ? [...completedRuns, problemRun]
      : completedRuns
  );
  // History may contain an older last-known active state while its refresh fails.
  const latestKnownRun = $derived<CrawlRun | undefined>(crawlRuns[0]);
  const activeRun = $derived(
    latestKnownRun && isActiveCrawlRun(latestKnownRun) ? latestKnownRun : undefined
  );
  const onrerun = $derived(
    !data.readonly && !activeRun
      ? () => {
          startDialogOpen = true;
        }
      : undefined
  );

  function selectProblemRun(run: CrawlRun | undefined) {
    selectedProblemRun = !run || run.id === latestCompletedRun?.id ? null : run;
  }

  async function showProblems(run: CrawlRun) {
    selectProblemRun(run);
    selectPageTab(tabs, "problems");
    await tick();
    problemHeading?.focus();
  }

  onMount(() => {
    let mounted = true;
    const interval = setInterval(async () => {
      if (pollingCrawlRuns) return;

      pollingCrawlRuns = true;
      const websiteId = data.website.id;
      const pageCrawlRuns = data.crawlRuns;
      try {
        const result = await pollWebsiteDetail(eneo, data.website, crawlRuns);
        if (!mounted || websiteId !== data.website.id || pageCrawlRuns !== data.crawlRuns) return;
        if (result.latestRun) {
          crawlRuns = mergeLatestCrawlRun(crawlRuns, result.latestRun);
        }
        // Status is independent of content availability. Retry an unsuccessful
        // content refresh on the next poll without reverting the terminal state.
        if (
          result.latestRun &&
          !isActiveCrawlRun(result.latestRun) &&
          result.latestRun.id !== contentRunId
        ) {
          try {
            const refreshedPage = await eneo.websites.indexedBlobs.listPage({
              id: websiteId,
              limit: PAGINATION.PAGE_SIZE
            });
            if (!mounted || websiteId !== data.website.id || pageCrawlRuns !== data.crawlRuns)
              return;
            infoBlobPage = refreshedPage;
            initialContent = null;
            contentRunId = result.latestRun.id;
          } catch {
            // Keep old content and retry, independently of the history refresh.
          }
        }
        if (result.latestRun && result.latestRun.id !== historyRunId) {
          const historyPage = await eneo.websites.crawlRuns.listPage({
            id: websiteId,
            limit: PAGINATION.PAGE_SIZE
          });
          if (!mounted || websiteId !== data.website.id || pageCrawlRuns !== data.crawlRuns) return;
          const history = historyPage.items;
          crawlRuns = mergeLatestCrawlRun(history, result.latestRun);
          nextCrawlRunCursor = historyPage.next_cursor ?? null;
          totalCrawlRunCount = historyPage.total_count;
          crawlRunPageGeneration += 1;
          loadingMoreCrawlRuns = false;
          // A lagging response is not a completed sync. Keep retrying until
          // history includes the run, without letting it overwrite latest status.
          if (history.some((run) => run.id === result.latestRun?.id)) {
            historyRunId = result.latestRun.id;
          }
        }
      } catch {
        // Preserve the last confirmed status. The next poll or a manual action retries.
      } finally {
        pollingCrawlRuns = false;
      }
    }, 10 * 1000);

    return () => {
      mounted = false;
      crawlRunPageGeneration += 1;
      clearInterval(interval);
    };
  });

  async function loadMoreCrawlRuns() {
    if (nextCrawlRunCursor === null || loadingMoreCrawlRuns) return;
    const generation = crawlRunPageGeneration;
    const cursor = nextCrawlRunCursor;
    const websiteId = data.website.id;
    loadingMoreCrawlRuns = true;
    try {
      const page = await eneo.websites.crawlRuns.listPage({
        id: websiteId,
        limit: PAGINATION.PAGE_SIZE,
        cursor
      });
      if (generation !== crawlRunPageGeneration || websiteId !== data.website.id) return;
      const knownIds = new Set(crawlRuns.map((run) => run.id));
      crawlRuns = [...crawlRuns, ...page.items.filter((run) => !knownIds.has(run.id))];
      nextCrawlRunCursor = page.next_cursor ?? null;
      totalCrawlRunCount = page.total_count;
    } catch (error) {
      if (generation === crawlRunPageGeneration && websiteId === data.website.id) {
        toastError(error, m.website_crawl_history_load_more_failed());
      }
    } finally {
      if (generation === crawlRunPageGeneration) loadingMoreCrawlRuns = false;
    }
  }
</script>

<svelte:head>
  <title
    >Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name} – {m.space_crawls_for_website(
      { websiteName: formatWebsiteName(data.website) }
    )}</title
  >
</svelte:head>

<Page.Root tabController={tabs}>
  <Page.Header>
    <Page.Title
      parent={{
        title: m.knowledge(),
        href: `/spaces/${$currentSpace.routeId}/knowledge?tab=websites`
      }}
      truncate
      title={formatWebsiteName(data.website)}
    ></Page.Title>
    <Page.Tabbar>
      <Page.TabTrigger tab="blobs">{m.source_tab_content()}</Page.TabTrigger>
      <Page.TabTrigger tab="problems">{m.source_tab_problems()}</Page.TabTrigger>
      <Page.TabTrigger tab="crawls">{m.source_tab_activity()}</Page.TabTrigger>
    </Page.Tabbar>
    {#if !data.readonly}
      <CrawlCreateRun
        website={data.website}
        {activeRun}
        hasHistory={crawlRuns.length > 0}
        bind:startDialogOpen
      ></CrawlCreateRun>
    {/if}
  </Page.Header>
  <Page.Main>
    <div class="pt-4 pr-4">
      <SourceStats columns={3}>
        <SourceStat label={m.website_source_latest_crawl()} tone="text">
          {#if latestKnownRun}
            <CrawlRunStatus run={latestKnownRun} />
          {:else}
            <span class="text-secondary font-normal">{m.this_website_not_crawled_before()}</span>
          {/if}
        </SourceStat>
        <SourceStat label={m.indexed_content()}>{infoBlobPage.total_count}</SourceStat>
        <SourceStat label={m.website_source_latest_completed()} tone="text">
          {latestCompletedRun
            ? formatDateTime(latestCompletedRun.finished_at ?? latestCompletedRun.created_at)
            : "–"}
        </SourceStat>
      </SourceStats>
    </div>
    <Page.Tab id="problems">
      {#if $tabs === "problems"}
        <div class="w-full py-5 pr-4">
          {#if problemRun}
            <div class="mb-3 flex flex-wrap items-center justify-between gap-3">
              <h2 bind:this={problemHeading} tabindex="-1" class="text-base font-semibold">
                {problemRun.id === latestCompletedRun?.id
                  ? m.website_source_latest_completed()
                  : m.website_source_previous_crawl()}
              </h2>
              {#if problemRunChoices.length > 1}
                <div class="flex flex-wrap items-center gap-2 text-sm">
                  <label for="problem-crawl">{m.website_source_choose_crawl()}</label>
                  <select
                    id="problem-crawl"
                    class="border-default bg-primary rounded-md border px-2 py-1.5"
                    value={problemRun.id}
                    onchange={(event) => {
                      const id = event.currentTarget.value;
                      selectProblemRun(problemRunChoices.find((run) => run.id === id));
                    }}
                  >
                    {#each problemRunChoices as run (run.id)}
                      <option value={run.id}>{formatDateTime(run.created_at)}</option>
                    {/each}
                  </select>
                </div>
              {/if}
            </div>
            <p class="text-secondary mb-5 text-sm">
              {m.website_source_problems_description({
                date: formatDateTime(problemRun.created_at)
              })}
            </p>
            {#key problemRun.id}
              <CrawlRunDetailsContent run={problemRun} open grouped />
            {/key}
            {#if onrerun}
              <div class="border-default mt-4 border-t pt-3">
                <p class="text-secondary mb-2 text-xs">{m.crawl_retry_whole_website_help()}</p>
                <Button variant="outline" onclick={onrerun}>
                  {m.crawl_retry_whole_website()}
                </Button>
              </div>
            {/if}
          {:else}
            <p class="text-secondary py-6 text-sm">{m.website_source_no_completed()}</p>
          {/if}
        </div>
      {/if}
    </Page.Tab>
    <Page.Tab id="crawls">
      {#if data.environment.integrationRequestFormUrl}
        <CrawlLimitations></CrawlLimitations>
      {/if}
      <CrawlRunActivity runs={crawlRuns} onshowProblems={showProblems} />
      {#if nextCrawlRunCursor !== null}
        <div class="mt-4 flex justify-center">
          <Button
            variant="outline"
            disabled={loadingMoreCrawlRuns}
            aria-busy={loadingMoreCrawlRuns}
            onclick={loadMoreCrawlRuns}
          >
            {#if loadingMoreCrawlRuns}
              <LoaderCircle class="animate-spin" aria-hidden="true" />
              {m.loading_more()}
            {:else}
              {m.website_crawl_history_load_more({
                current: crawlRuns.length,
                total: totalCrawlRunCount
              })}
            {/if}
          </Button>
        </div>
      {/if}
    </Page.Tab>
    <Page.Tab id="blobs">
      {#if data.environment.integrationRequestFormUrl}
        <CrawlLimitations></CrawlLimitations>
      {/if}
      {#if latestCompletedRun && hasCrawlIssues(latestCompletedRun)}
        {@const latest = latestCompletedRun}
        <div
          class="border-default mb-4 flex flex-wrap items-start justify-between gap-3 rounded-lg border p-4"
        >
          <div class="flex min-w-0 items-start gap-3">
            {#if isCompletedWithMissingResources(latest)}
              <Info class="text-secondary mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {:else}
              <TriangleAlert
                class="text-warning-stronger mt-0.5 size-4 shrink-0"
                aria-hidden="true"
              />
            {/if}
            <div>
              <h2 class="text-sm font-semibold">
                {isCompletedWithMissingResources(latest)
                  ? m.crawl_content_has_missing()
                  : m.crawl_content_has_failures()}
              </h2>
              <p class="text-secondary mt-1 max-w-prose text-sm">
                {m.crawl_content_failure_description({ date: formatDateTime(latest.created_at) })}
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" onclick={() => showProblems(latest)}>
            {m.website_source_see_problems()}
          </Button>
        </div>
      {/if}
      {#if $tabs === "blobs"}
        <WebsiteContent
          websiteId={data.website.id}
          initialPage={infoBlobPage}
          revision={contentRunId}
          bind:prefix={contentFilters.prefix}
          bind:query={contentFilters.q}
          bind:initialContent
        />
      {/if}
    </Page.Tab>
  </Page.Main>
</Page.Root>
