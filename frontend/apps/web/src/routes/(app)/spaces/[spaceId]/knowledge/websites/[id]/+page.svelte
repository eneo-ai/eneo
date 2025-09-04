<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { Page } from "$lib/components/layout";
  import CrawlRunsTable from "./CrawlRunsTable.svelte";
  import { onMount } from "svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import BlobTable from "../../collections/[collectionId]/BlobTable.svelte";
  import CrawlLimitations from "./CrawlLimitations.svelte";
  import { formatWebsiteName } from "$lib/core/formatting/formatWebsiteName.js";
  import CrawlCreateRun from "./CrawlCreateRun.svelte";

  export let data;

  onMount(() => {
    const interval = setInterval(() => {
      invalidate("crawlruns:list");
    }, 30 * 1000);

    return () => clearInterval(interval);
  });

  const {
    state: { currentSpace }
  } = getSpacesManager();
</script>

<svelte:head>
  <title
    >Eneo.ai – {data.currentSpace.personal ? "Personal" : data.currentSpace.name} – Crawls for {formatWebsiteName(
      data.website
    )}</title
  >
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: "Knowledge",
        href: `/spaces/${$currentSpace.routeId}/knowledge?tab=websites`
      }}
      truncate
      title={formatWebsiteName(data.website)}
    ></Page.Title>
    <Page.Tabbar>
      <Page.TabTrigger tab="crawls">Crawls</Page.TabTrigger>
      <Page.TabTrigger tab="blobs">Indexed content</Page.TabTrigger>
    </Page.Tabbar>
    {#if !data.readonly}
      <CrawlCreateRun
        website={data.website}
        isDisabled={data.crawlRuns.some(
          (run) => run.status === "in progress" || run.status === "queued"
        )}
      ></CrawlCreateRun>
    {/if}
  </Page.Header>
  <Page.Main>
    <Page.Tab id="crawls">
      {#if data.environment.integrationRequestFormUrl}
        <CrawlLimitations></CrawlLimitations>
      {/if}
      <CrawlRunsTable runs={data.crawlRuns} />
    </Page.Tab>
    <Page.Tab id="blobs">
      {#if data.environment.integrationRequestFormUrl}
        <CrawlLimitations></CrawlLimitations>
      {/if}
      <BlobTable blobs={data.infoBlobs} canEdit={false}></BlobTable>
    </Page.Tab>
  </Page.Main>
</Page.Root>
