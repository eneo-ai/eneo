<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { PAGINATION } from "$lib/core/constants";
  import { toastError } from "$lib/core/errors";
  import CrawlRunsTable from "./CrawlRunsTable.svelte";
  import { onMount } from "svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import BlobTable from "../../collections/[collectionId]/BlobTable.svelte";
  import CrawlLimitations from "./CrawlLimitations.svelte";
  import { formatWebsiteName } from "$lib/core/formatting/formatWebsiteName.js";
  import CrawlCreateRun from "./CrawlCreateRun.svelte";
  import { m } from "$lib/paraglide/messages";
  import { isActiveCrawlRun } from "$lib/features/knowledge/crawlRunState";
  import { LoaderCircle } from "lucide-svelte";
  import type { WebsiteInfoBlobPage } from "@eneo/eneo-js";
  import { mergeLatestCrawlRun, pollWebsiteDetail } from "./websiteDetailPolling";

  export let data;

  const eneo = getEneo();
  let serverCrawlRuns = data.crawlRuns;
  let crawlRuns = data.crawlRuns;
  let serverInfoBlobPage = data.infoBlobPage;
  let infoBlobs = [...data.infoBlobPage.items];
  let nextInfoBlobCursor = data.infoBlobPage.next_cursor ?? null;
  let totalInfoBlobCount = data.infoBlobPage.total_count;
  let loadingMoreInfoBlobs = false;
  let pollingCrawlRuns = false;
  let historyRunId = data.crawlRuns.at(-1)?.id;
  let contentRunId = data.crawlRuns.filter((run) => !isActiveCrawlRun(run)).at(-1)?.id;

  $: if (data.crawlRuns !== serverCrawlRuns) {
    serverCrawlRuns = data.crawlRuns;
    crawlRuns = data.crawlRuns;
    historyRunId = data.crawlRuns.at(-1)?.id;
  }

  $: if (data.infoBlobPage !== serverInfoBlobPage) {
    serverInfoBlobPage = data.infoBlobPage;
    replaceInfoBlobPage(data.infoBlobPage);
    contentRunId = data.crawlRuns.filter((run) => !isActiveCrawlRun(run)).at(-1)?.id;
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
        crawlRuns = result.crawlRuns;
        // Status is independent of content availability. Retry an unsuccessful
        // content refresh on the next poll without reverting the terminal state.
        if (
          result.latestRun &&
          !isActiveCrawlRun(result.latestRun) &&
          result.latestRun.id !== contentRunId
        ) {
          try {
            const infoBlobPage = await eneo.websites.indexedBlobs.listPage({
              id: websiteId,
              limit: PAGINATION.PAGE_SIZE
            });
            if (!mounted || websiteId !== data.website.id || pageCrawlRuns !== data.crawlRuns)
              return;
            replaceInfoBlobPage(infoBlobPage);
            contentRunId = result.latestRun.id;
          } catch {
            // Keep old content and retry, independently of the history refresh.
          }
        }
        if (result.latestRun && result.latestRun.id !== historyRunId) {
          const history = [...(await eneo.websites.crawlRuns.list({ id: websiteId }))].reverse();
          if (!mounted || websiteId !== data.website.id || pageCrawlRuns !== data.crawlRuns) return;
          crawlRuns = mergeLatestCrawlRun(history, result.latestRun);
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
      clearInterval(interval);
    };
  });

  const {
    state: { currentSpace }
  } = getSpacesManager();

  // History may contain an older last-known active state while its refresh fails.
  $: latestKnownRun = crawlRuns.at(-1);
  $: activeRun = latestKnownRun && isActiveCrawlRun(latestKnownRun) ? latestKnownRun : undefined;

  function replaceInfoBlobPage(page: WebsiteInfoBlobPage) {
    infoBlobs = [...page.items];
    nextInfoBlobCursor = page.next_cursor ?? null;
    totalInfoBlobCount = page.total_count;
  }

  async function loadMoreInfoBlobs() {
    if (nextInfoBlobCursor === null || loadingMoreInfoBlobs) return;

    loadingMoreInfoBlobs = true;
    try {
      const page = await eneo.websites.indexedBlobs.listPage({
        id: data.website.id,
        limit: PAGINATION.PAGE_SIZE,
        cursor: nextInfoBlobCursor
      });
      infoBlobs = [...infoBlobs, ...page.items];
      nextInfoBlobCursor = page.next_cursor ?? null;
      totalInfoBlobCount = page.total_count;
    } catch (error) {
      toastError(error, m.website_indexed_content_load_more_failed());
    } finally {
      loadingMoreInfoBlobs = false;
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

<Page.Root>
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
      <Page.TabTrigger tab="crawls">{m.crawls()}</Page.TabTrigger>
      <Page.TabTrigger tab="blobs">{m.indexed_content()}</Page.TabTrigger>
    </Page.Tabbar>
    {#if !data.readonly}
      <CrawlCreateRun website={data.website} {activeRun} hasHistory={crawlRuns.length > 0}
      ></CrawlCreateRun>
    {/if}
  </Page.Header>
  <Page.Main>
    <Page.Tab id="crawls">
      {#if data.environment.integrationRequestFormUrl}
        <CrawlLimitations></CrawlLimitations>
      {/if}
      <CrawlRunsTable runs={crawlRuns} />
    </Page.Tab>
    <Page.Tab id="blobs">
      {#if data.environment.integrationRequestFormUrl}
        <CrawlLimitations></CrawlLimitations>
      {/if}
      <BlobTable
        blobs={infoBlobs}
        canEdit={false}
        resourceName={m.website_indexed_content_resource()}
        emptyMessage={m.website_no_indexed_content()}
      ></BlobTable>
      {#if nextInfoBlobCursor !== null}
        <div class="mt-4 flex justify-center">
          <Button
            variant="outline"
            disabled={loadingMoreInfoBlobs}
            aria-busy={loadingMoreInfoBlobs}
            onclick={loadMoreInfoBlobs}
          >
            {#if loadingMoreInfoBlobs}
              <LoaderCircle class="animate-spin" aria-hidden="true" />
              {m.loading_more()}
            {:else}
              {m.website_indexed_content_load_more({
                current: infoBlobs.length,
                total: totalInfoBlobCount
              })}
            {/if}
          </Button>
        </div>
      {/if}
    </Page.Tab>
  </Page.Main>
</Page.Root>
