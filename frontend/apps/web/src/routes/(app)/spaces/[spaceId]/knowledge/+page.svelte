<script lang="ts">
  import { Page } from "$lib/components/layout";
  import CollectionEditor from "./collections/CollectionEditor.svelte";
  import CollectionTable from "./collections/CollectionTable.svelte";
  import WebsiteEditor from "./websites/WebsiteEditor.svelte";
  import WebsiteTable from "./websites/WebsiteTable.svelte";
  import { writable } from "svelte/store";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getIntric } from "$lib/core/Intric";
  import { Button } from "@intric/ui";
  import { IconLinkExternal } from "@intric/icons/link-external";
  import { IconRefresh } from "@intric/icons/refresh";
  import IntegrationsTable from "./integrations/IntegrationsTable.svelte";
  import ImportKnowledgeDialog from "$lib/features/integrations/components/import/ImportKnowledgeDialog.svelte";
  export let data;

  const intric = getIntric();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  let selectedTab = writable<string>();
  let showIntegrationsNotice = data.environment.integrationRequestFormUrl !== undefined;

  // Website selection state (shared with WebsiteTable)
  let selectedWebsiteIds = writable<Set<string>>(new Set());
  let isBulkRecrawling = false;

  // Bulk recrawl handler
  async function bulkRecrawl() {
    if ($selectedWebsiteIds.size === 0) return;

    isBulkRecrawling = true;
    try {
      const websiteIds = Array.from($selectedWebsiteIds);

      const response = await intric.websites.bulkRun({
        website_ids: websiteIds
      });

      // Only show alert if there were errors
      if (response.failed > 0) {
        alert(
          `${response.queued} website${response.queued > 1 ? 's' : ''} queued, ${response.failed} failed.\n` +
          `Check console for error details.`
        );
        console.error("Bulk recrawl errors:", response.errors);
      }

      // Clear selection and refresh
      $selectedWebsiteIds = new Set();
      refreshCurrentSpace();
    } catch (e) {
      alert("Failed to trigger bulk recrawl: " + e);
      console.error(e);
    }
    isBulkRecrawling = false;
  }

  $: userCanSeeCollections = $currentSpace.hasPermission("read", "collection");
  $: userCanSeeWebsites = $currentSpace.hasPermission("read", "website");
  $: userCanSeeIntegrations =
    $currentSpace.hasPermission("read", "integrationKnowledge") &&
    data.availableIntegrations.length > 0;
</script>

<svelte:head>
  <title
    >Eneo.ai – {data.currentSpace.personal ? "Personal" : data.currentSpace.name} – Knowledge</title
  >
</svelte:head>

<Page.Root tabController={selectedTab}>
  <Page.Header>
    <Page.Title title="Knowledge"></Page.Title>
    <Page.Tabbar>
      {#if userCanSeeCollections}
        <Page.TabTrigger tab="collections">Collections</Page.TabTrigger>
      {/if}
      {#if userCanSeeWebsites}
        <Page.TabTrigger tab="websites">Websites</Page.TabTrigger>
      {/if}
      {#if userCanSeeIntegrations}
        <Page.TabTrigger tab="integrations">Integrations</Page.TabTrigger>
      {/if}
    </Page.Tabbar>
    <div class="flex-grow"></div>
    <Page.Flex>
      {#if $selectedTab === "collections" && $currentSpace.hasPermission("create", "collection")}
        <CollectionEditor mode="create" collection={undefined}></CollectionEditor>
      {:else if $selectedTab === "websites" && $currentSpace.hasPermission("create", "website")}
        {#if $selectedWebsiteIds.size > 0}
          <Button
            variant="primary"
            on:click={bulkRecrawl}
            disabled={isBulkRecrawling}
          >
            <IconRefresh size="sm" />
            {isBulkRecrawling ? 'Syncing...' : `Sync selected (${$selectedWebsiteIds.size})`}
          </Button>
        {:else}
          <WebsiteEditor mode="create"></WebsiteEditor>
        {/if}
      {:else if $selectedTab === "integrations" && $currentSpace.hasPermission("create", "integrationKnowledge") && data.availableIntegrations.length > 0}
        <ImportKnowledgeDialog></ImportKnowledgeDialog>
      {/if}
    </Page.Flex>
  </Page.Header>
  <Page.Main>
    {#if userCanSeeCollections}
      <Page.Tab id="collections">
        <CollectionTable></CollectionTable>
      </Page.Tab>
    {/if}
    {#if userCanSeeWebsites}
      <Page.Tab id="websites">
        <WebsiteTable bind:selectedWebsiteIds></WebsiteTable>
      </Page.Tab>
    {/if}
    {#if userCanSeeIntegrations}
      <Page.Tab id="integrations">
        {#if showIntegrationsNotice}
          <div class="border-dimmer hidden border-b py-3 pr-3 lg:block">
            <div
              class="label-neutral border-label-default bg-label-dimmer text-label-stronger flex items-center gap-8 rounded-lg border px-4 py-3 shadow"
            >
              <div class="flex flex-col">
                <span class="font-mono text-xs uppercase">Beta version</span>
                <span class="text-xl font-extrabold">Integrations</span>
              </div>
              <p class="-mt-[0.1rem] max-w-[85ch] pl-6 leading-[1.3rem]">
                This is an early version of our upcoming integrations feature. It might be unstable
                during the beta period. <a
                  target="_blank"
                  rel="noreferrer"
                  class="hover:bg-label-stronger hover:text-label-dimmer inline items-center gap-1 underline"
                  href={data.environment.integrationRequestFormUrl}
                  >Please leave feedback on this feature or request other integrations
                </a>
                <IconLinkExternal class="-mt-0.5 inline" size="sm"></IconLinkExternal>
              </p>
              <div class="flex-grow"></div>
              <Button
                variant="outlined"
                class="min-w-24"
                on:click={() => {
                  showIntegrationsNotice = false;
                }}>Dismiss</Button
              >
            </div>
          </div>
        {/if}
        <IntegrationsTable></IntegrationsTable>
      </Page.Tab>
    {/if}
  </Page.Main>
</Page.Root>
