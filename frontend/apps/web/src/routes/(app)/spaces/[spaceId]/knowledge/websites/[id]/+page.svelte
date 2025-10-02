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
  import { m } from "$lib/paraglide/messages";

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
    >Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name} – {m.crawls()} for {formatWebsiteName(
      data.website
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
    <CrawlCreateRun
      website={data.website}
      isDisabled={data.crawlRuns.some(
        (run) => run.status === "in progress" || run.status === "queued"
      )}
    ></CrawlCreateRun>
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
