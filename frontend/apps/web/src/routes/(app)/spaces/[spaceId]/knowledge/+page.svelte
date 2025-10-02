<script lang="ts">
  import { Page } from "$lib/components/layout";
  import CollectionEditor from "./collections/CollectionEditor.svelte";
  import CollectionTable from "./collections/CollectionTable.svelte";
  import WebsiteEditor from "./websites/WebsiteEditor.svelte";
  import WebsiteTable from "./websites/WebsiteTable.svelte";
  import { writable } from "svelte/store";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { Button } from "@intric/ui";
  import { IconLinkExternal } from "@intric/icons/link-external";
  import IntegrationsTable from "./integrations/IntegrationsTable.svelte";
  import ImportKnowledgeDialog from "$lib/features/integrations/components/import/ImportKnowledgeDialog.svelte";
  import { m } from "$lib/paraglide/messages";
  export let data;

  const {
    state: { currentSpace }
  } = getSpacesManager();

  let selectedTab = writable<string>();
  let showIntegrationsNotice = data.environment.integrationRequestFormUrl !== undefined;

  $: userCanSeeCollections = $currentSpace.hasPermission("read", "collection");
  $: userCanSeeWebsites = $currentSpace.hasPermission("read", "website");
  $: userCanSeeIntegrations =
    $currentSpace.hasPermission("read", "integrationKnowledge") &&
    data.availableIntegrations.length > 0;
</script>

<svelte:head>
  <title>Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name} – {m.knowledge()}</title>
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
        <WebsiteEditor mode="create"></WebsiteEditor>
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
        <WebsiteTable></WebsiteTable>
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
                {m.integrations_beta_notice()} <a
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
        <IntegrationsTable></IntegrationsTable>
      </Page.Tab>
    {/if}
  </Page.Main>
</Page.Root>
