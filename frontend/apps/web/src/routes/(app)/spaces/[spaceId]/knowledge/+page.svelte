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
  import SyncHistoryDialog from "./integrations/SyncHistoryDialog.svelte";
  import ImportKnowledgeDialog from "$lib/features/integrations/components/import/ImportKnowledgeDialog.svelte";
  import { m } from "$lib/paraglide/messages";
  import type { IntegrationKnowledge } from "@intric/intric-js";
  import { jobCompletionEvents } from "$lib/features/jobs/JobManager";

  let { data } = $props<{ data: any }>();

  const intric = getIntric();
  const {
    state: { currentSpace },
    refreshCurrentSpace
  } = getSpacesManager();

  // Listen for job completion events and refresh knowledge
  $effect(() => {
    const event = $jobCompletionEvents;
    if (event) {
      console.log("Knowledge page: Job completion event received, refreshing knowledge");
      refreshCurrentSpace("knowledge");
    }
  });

  let selectedTab = writable<string>();
  let showIntegrationsNotice = data.environment.integrationRequestFormUrl !== undefined;
  let selectedIntegrationForSyncHistory: IntegrationKnowledge | null = $state(null);
  let showSyncHistoryDialog = $state(false);
  let isOrgSpace = $currentSpace.organization;
  let isPersonalSpace = $currentSpace.personal;

  // Check if user has admin permission
  let isAdmin = data.user?.predefined_roles?.some((role: any) =>
    role.permissions?.includes('admin')
  ) ?? false;

  function handleSelectIntegration(integration: IntegrationKnowledge) {
    selectedIntegrationForSyncHistory = integration;
    showSyncHistoryDialog = true;
  }

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


  let userCanSeeCollections = $derived($currentSpace.hasPermission("read", "collection"));
  let userCanSeeWebsites = $derived($currentSpace.hasPermission("read", "website"));
  // Only show integrations in personal and organization spaces, not in shared spaces
  let userCanSeeIntegrations = $derived(
    $currentSpace.hasPermission("read", "integrationKnowledge") &&
    (isPersonalSpace || isOrgSpace)
  );

  // Reset selected integration when dialog closes
  $effect(() => {
    if (!showSyncHistoryDialog) {
      selectedIntegrationForSyncHistory = null;
    }
  });
</script>

<svelte:head>
  <title
    >Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name} – {m.knowledge()}</title
  >
</svelte:head>

<Page.Root tabController={selectedTab}>
  <Page.Header>
    <Page.Title title={m.knowledge()}></Page.Title>
    <Page.Tabbar>
      {#if userCanSeeCollections}
        <Page.TabTrigger tab="collections">{m.collections()}</Page.TabTrigger>
      {/if}
      {#if userCanSeeWebsites}
        <Page.TabTrigger tab="websites">{m.websites()}</Page.TabTrigger>
      {/if}
      {#if userCanSeeIntegrations}
        <Page.TabTrigger tab="integrations">{m.integrations()}</Page.TabTrigger>
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
            {isBulkRecrawling
              ? m.syncing()
              : m.sync_selected({ count: $selectedWebsiteIds.size })}
          </Button>
        {:else}
          <WebsiteEditor mode="create"></WebsiteEditor>
        {/if}
      {:else if $selectedTab === "integrations" && $currentSpace.hasPermission("create", "integrationKnowledge")}
        {#if data.availableIntegrations.length > 0}
          <ImportKnowledgeDialog></ImportKnowledgeDialog>
        {:else}
          {#if isOrgSpace}
            {#if isAdmin}
              <Button variant="primary" onclick={() => window.location.href = '/admin/integrations?tab=providers'}>
                {m.configure_integrations()}
              </Button>
            {:else}
              <div class="text-secondary text-sm italic">
                Organization-wide integrations require admin permissions
              </div>
            {/if}
          {:else}
            <Button variant="primary" onclick={() => window.location.href = '/account/integrations?tab=providers'}>
              {m.configure_integrations()}
            </Button>
          {/if}
        {/if}
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
                <span class="font-mono text-xs uppercase">{m.beta_version()}</span>
                <span class="text-xl font-extrabold">{m.integrations()}</span>
              </div>
              <p class="-mt-[0.1rem] max-w-[85ch] pl-6 leading-[1.3rem]">
                {m.integrations_beta_notice()}
                <a
                  target="_blank"
                  rel="noreferrer"
                  class="hover:bg-label-stronger hover:text-label-dimmer inline items-center gap-1 underline"
                  href={data.environment.integrationRequestFormUrl}
                  >{m.request_integrations_feedback()}
                </a>
                <IconLinkExternal class="-mt-0.5 inline" size="sm"></IconLinkExternal>
              </p>
              <div class="flex-grow"></div>
              <Button
                variant="outlined"
                class="min-w-24"
                on:click={() => {
                  showIntegrationsNotice = false;
                }}>{m.dismiss()}</Button
              >
            </div>
          </div>
        {/if}
        <IntegrationsTable onSelectIntegrationForSyncHistory={handleSelectIntegration}></IntegrationsTable>
        <SyncHistoryDialog
          knowledge={selectedIntegrationForSyncHistory}
          bind:open={showSyncHistoryDialog}
        ></SyncHistoryDialog>
      </Page.Tab>
    {/if}
  </Page.Main>
</Page.Root>
