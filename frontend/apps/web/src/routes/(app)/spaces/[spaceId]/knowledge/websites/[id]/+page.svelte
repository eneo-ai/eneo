<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { PAGINATION } from "$lib/core/constants";
  import { toastError } from "$lib/core/errors";
  import CrawlRunActivity from "./CrawlRunActivity.svelte";
  import { onMount, tick } from "svelte";
  import { page } from "$app/state";
  import { replaceState } from "$app/navigation";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import WebsiteContent from "$lib/features/knowledge/WebsiteContent.svelte";
  import CrawlRunDetailsContent from "$lib/features/knowledge/CrawlRunDetailsContent.svelte";
  import CrawlRunStatus from "$lib/features/knowledge/CrawlRunStatus.svelte";
  import { writable } from "svelte/store";
  import CrawlLimitations from "./CrawlLimitations.svelte";
  import { formatDateTime } from "$lib/core/formatting/dateTime";
  import { formatWebsiteName } from "$lib/core/formatting/formatWebsiteName.js";
  import CrawlCreateRun from "./CrawlCreateRun.svelte";
  import { m } from "$lib/paraglide/messages";
  import {
    hasCrawlIssues,
    isCompletedWithMissingResources,
    isActiveCrawlRun
  } from "$lib/features/knowledge/crawlRunState";
  import { Info, LoaderCircle, TriangleAlert } from "@lucide/svelte";
  import type { CrawlRun } from "@eneo/eneo-js";
  import { mergeLatestCrawlRun, pollWebsiteDetail } from "./websiteDetailPolling";

  export let data;

  const eneo = getEneo();
  const tabs = writable<string>();
  let startDialogOpen = false;
  let selectedProblemRunId: string | null = null;
  let problemHeading: HTMLHeadingElement | undefined;
  $: completedRuns = crawlRuns.filter((run) => !isActiveCrawlRun(run));
  $: latestCompletedRun = completedRuns[0];
  $: problemRun =
    completedRuns.find((run) => run.id === selectedProblemRunId) ?? latestCompletedRun;
  $: onrerun =
    !data.readonly && !activeRun
      ? () => {
          startDialogOpen = true;
        }
      : undefined;

  async function showProblems(run: CrawlRun) {
    selectedProblemRunId = run.id === latestCompletedRun?.id ? null : run.id;
    tabs.set("problems");
    const url = new URL(page.url);
    url.searchParams.set("tab", "problems");
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- same page, changing only its tab
    replaceState(url, { ...page.state, tab: "problems" });
    await tick();
    problemHeading?.focus();
  }

  let serverCrawlRuns = data.crawlRuns;
  let crawlRuns = data.crawlRuns;
  let nextCrawlRunCursor = data.nextCrawlRunCursor;
  let totalCrawlRunCount = data.totalCrawlRunCount;
  let crawlRunPageGeneration = 0;
  let loadingMoreCrawlRuns = false;
  let serverInfoBlobPage = data.infoBlobPage;
  let infoBlobPage = data.infoBlobPage;
  let pollingCrawlRuns = false;
  let historyRunId = data.crawlRuns[0]?.id;
  let contentRunId = data.crawlRuns.find((run) => !isActiveCrawlRun(run))?.id;

  $: if (data.crawlRuns !== serverCrawlRuns) {
    serverCrawlRuns = data.crawlRuns;
    crawlRuns = data.crawlRuns;
    nextCrawlRunCursor = data.nextCrawlRunCursor;
    totalCrawlRunCount = data.totalCrawlRunCount;
    crawlRunPageGeneration += 1;
    loadingMoreCrawlRuns = false;
    historyRunId = data.crawlRuns[0]?.id;
  }

  $: if (data.infoBlobPage !== serverInfoBlobPage) {
    serverInfoBlobPage = data.infoBlobPage;
    infoBlobPage = data.infoBlobPage;
    contentRunId = data.crawlRuns.find((run) => !isActiveCrawlRun(run))?.id;
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

  const {
    state: { currentSpace }
  } = getSpacesManager();

  // History may contain an older last-known active state while its refresh fails.
  $: latestKnownRun = crawlRuns[0];
  $: activeRun = latestKnownRun && isActiveCrawlRun(latestKnownRun) ? latestKnownRun : undefined;

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
    <div class="border-default grid gap-4 border-b py-4 pr-4 sm:grid-cols-3">
      <div>
        <p class="text-secondary text-xs">{m.website_source_latest_crawl()}</p>
        <div class="mt-1">
          {#if latestKnownRun}<CrawlRunStatus run={latestKnownRun} />{:else}<span
              class="text-secondary text-sm">{m.this_website_not_crawled_before()}</span
            >{/if}
        </div>
      </div>
      <div>
        <p class="text-secondary text-xs">{m.indexed_content()}</p>
        <p class="mt-1 font-semibold tabular-nums">{infoBlobPage.total_count}</p>
      </div>
      <div>
        <p class="text-secondary text-xs">{m.website_source_latest_completed()}</p>
        <p class="mt-1 text-sm">
          {latestCompletedRun
            ? formatDateTime(latestCompletedRun.finished_at ?? latestCompletedRun.created_at)
            : "–"}
        </p>
      </div>
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
              {#if completedRuns.length > 1}
                <div class="flex flex-wrap items-center gap-2 text-sm">
                  <label for="problem-crawl">{m.website_source_choose_crawl()}</label>
                  <select
                    id="problem-crawl"
                    class="border-default bg-primary rounded-md border px-2 py-1.5"
                    value={problemRun.id}
                    onchange={(event) => {
                      selectedProblemRunId =
                        event.currentTarget.value === latestCompletedRun?.id
                          ? null
                          : event.currentTarget.value;
                    }}
                  >
                    {#each completedRuns as run (run.id)}
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
        <div
          class="border-default mb-4 flex flex-wrap items-start justify-between gap-3 rounded-lg border p-4"
        >
          <div class="flex min-w-0 items-start gap-3">
            {#if isCompletedWithMissingResources(latestCompletedRun)}
              <Info class="text-secondary mt-0.5 size-4 shrink-0" aria-hidden="true" />
            {:else}
              <TriangleAlert
                class="text-warning-stronger mt-0.5 size-4 shrink-0"
                aria-hidden="true"
              />
            {/if}
            <div>
              <h2 class="text-sm font-semibold">
                {isCompletedWithMissingResources(latestCompletedRun)
                  ? m.crawl_content_has_missing()
                  : m.crawl_content_has_failures()}
              </h2>
              <p class="text-secondary mt-1 max-w-prose text-sm">
                {m.crawl_content_failure_description({
                  date: formatDateTime(latestCompletedRun.created_at)
                })}
              </p>
            </div>
          </div>
          <Button variant="outline" size="sm" onclick={() => showProblems(latestCompletedRun)}>
            {m.website_source_see_problems()}
          </Button>
        </div>
      {/if}
      {#if $tabs === "blobs"}
        <WebsiteContent websiteId={data.website.id} initialPage={infoBlobPage} />
      {/if}
    </Page.Tab>
  </Page.Main>
</Page.Root>
