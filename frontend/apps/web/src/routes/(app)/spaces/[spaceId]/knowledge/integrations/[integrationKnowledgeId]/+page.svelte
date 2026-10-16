<script lang="ts">
  import { goto } from "$app/navigation";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import { IconLinkExternal } from "@eneo/icons/link-external";
  import { Page } from "$lib/components/layout";
  import { Button } from "$lib/components/ui/button/index.js";
  import { previewLinkLabel } from "$lib/features/integrations/IntegrationData";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { m } from "$lib/paraglide/messages";
  import IntegrationActions from "../IntegrationActions.svelte";
  import SyncHistoryDialog from "../SyncHistoryDialog.svelte";
  import IntegrationDocumentsView from "./IntegrationDocumentsView.svelte";

  let { data } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  // Re-read the item from the space so renames and finished syncs show without a reload.
  let knowledge = $derived<IntegrationKnowledge>(
    $currentSpace.knowledge.integrationKnowledge.find(
      (item: IntegrationKnowledge) => item.id === data.knowledge.id
    ) ?? data.knowledge
  );

  let parents = $derived.by(() => {
    const integrations = {
      title: m.integrations(),
      href: `/spaces/${$currentSpace.routeId}/knowledge?tab=integrations`
    };
    if (!knowledge.wrapper_id) return [integrations];
    return [
      integrations,
      {
        title: knowledge.wrapper_name || m.integrations(),
        href: `/spaces/${$currentSpace.routeId}/knowledge/integrations/wrapper/${knowledge.wrapper_id}`
      }
    ];
  });
  let parent = $derived(parents[parents.length - 1]);

  // The item was deleted from its actions menu: this page has nothing left to show.
  // The space store can still predate a fresh import, so only a disappearance counts.
  let seenInSpaceId: string | null = null;
  $effect(() => {
    const stillInSpace = $currentSpace.knowledge.integrationKnowledge.some(
      (item: IntegrationKnowledge) => item.id === data.knowledge.id
    );
    if (stillInSpace) {
      seenInSpaceId = data.knowledge.id;
    } else if (
      seenInSpaceId === data.knowledge.id &&
      $currentSpace.id === data.knowledge.space_id
    ) {
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic space route
      void goto(parent.href);
    }
  });

  let showSyncHistoryDialog = $state(false);
</script>

<svelte:head>
  <title>
    Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name} – {knowledge.name}
  </title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title {parents} title={knowledge.name} truncate></Page.Title>
    <div class="flex-grow"></div>
    <Page.Flex>
      {#if knowledge.url}
        <Button variant="outline" href={knowledge.url} target="_blank" rel="noopener noreferrer">
          {previewLinkLabel(knowledge.integration_type)}
          <IconLinkExternal size="sm" data-icon="inline-end" />
        </Button>
      {/if}
      <IntegrationActions knowledgeItem={knowledge} />
    </Page.Flex>
  </Page.Header>
  <Page.Main>
    <!-- The view seeds its table from the load data once; another item means a fresh view. -->
    {#key data.knowledge.id}
      <IntegrationDocumentsView
        {knowledge}
        space={$currentSpace}
        initialDocuments={data.documents}
        initialSkipped={data.skipped}
        initialTab={data.initialTab}
        onShowSyncHistory={() => (showSyncHistoryDialog = true)}
      />
    {/key}
    <SyncHistoryDialog {knowledge} bind:open={showSyncHistoryDialog}></SyncHistoryDialog>
  </Page.Main>
</Page.Root>
