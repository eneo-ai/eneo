<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { Table } from "@intric/ui";
  import { createRender } from "svelte-headless-table";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { derived } from "svelte/store";
  import type { IntegrationKnowledge } from "@intric/intric-js";
  import IntegrationNameCell from "../../IntegrationNameCell.svelte";
  import IntegrationSyncStatusCell from "../../IntegrationSyncStatusCell.svelte";
  import IntegrationActions from "../../IntegrationActions.svelte";
  import SharePointWrapperActions from "../../SharePointWrapperActions.svelte";
  import SyncHistoryDialog from "../../SyncHistoryDialog.svelte";
  import { integrationData } from "$lib/features/integrations/IntegrationData";
  import { m } from "$lib/paraglide/messages";

  let { data } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  // Re-derive items from currentSpace to stay reactive after renames/deletes/syncs
  const wrapperItems = derived(currentSpace, ($currentSpace) =>
    $currentSpace.knowledge.integrationKnowledge.filter(
      (k) => k.wrapper_id === data.wrapperId && k.space_id === $currentSpace.id
    )
  );

  const wrapperName = derived(wrapperItems, ($wrapperItems) => {
    if ($wrapperItems.length > 0) {
      const first = $wrapperItems[0];
      if (typeof first.wrapper_name === "string" && first.wrapper_name.trim().length > 0) {
        return first.wrapper_name;
      }
      return first.name;
    }
    return data.wrapperName;
  });

  // Wrapper permissions
  const wrapperPermissions = derived(wrapperItems, ($wrapperItems) => {
    if ($wrapperItems.length === 0) return { canEdit: false, canDelete: false };
    const permissions = $wrapperItems[0].permissions ?? [];
    return {
      canEdit: permissions.includes("edit"),
      canDelete: permissions.includes("delete")
    };
  });

  // Sync history state
  let selectedIntegrationForSyncHistory: IntegrationKnowledge | null = $state(null);
  let showSyncHistoryDialog = $state(false);

  function handleSelectIntegration(integration: IntegrationKnowledge) {
    selectedIntegrationForSyncHistory = integration;
    showSyncHistoryDialog = true;
  }

  $effect(() => {
    if (!showSyncHistoryDialog) {
      selectedIntegrationForSyncHistory = null;
    }
  });

  // Table setup
  const table = Table.createWithStore(wrapperItems);

  const viewModel = table.createViewModel([
    table.column({
      header: m.name(),
      accessor: (item) => item,
      cell: (item) => {
        return createRender(IntegrationNameCell, {
          knowledge: item.value
        });
      }
    }),

    table.column({
      header: m.status(),
      accessor: (item) => item,
      cell: (item) => {
        return createRender(IntegrationSyncStatusCell, {
          knowledge: item.value,
          onShowSyncHistory: () => handleSelectIntegration(item.value)
        });
      }
    }),

    table.column({
      accessor: (item) => item,
      header: m.link(),
      cell: (item) => {
        const labelKey = integrationData[item.value.integration_type].previewLinkLabel;
        const translatedLabel = m[labelKey as keyof typeof m]?.() ?? labelKey;
        return createRender(Table.ButtonCell, {
          link: item.value.url ?? "",
          label: translatedLabel,
          linkIsExternal: true
        });
      }
    }),

    table.columnActions({
      cell: (item) => {
        return createRender(IntegrationActions, {
          knowledgeItem: item.value
        });
      }
    })
  ]);
</script>

<svelte:head>
  <title>
    Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name} – {$wrapperName}
  </title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      parent={{
        title: m.integrations(),
        href: `/spaces/${$currentSpace.routeId}/knowledge?tab=integrations`
      }}
      title={$wrapperName}
    ></Page.Title>
    <div class="flex-grow"></div>
    <Page.Flex>
      {#if $wrapperPermissions.canEdit || $wrapperPermissions.canDelete}
        <SharePointWrapperActions
          wrapperId={data.wrapperId}
          wrapperName={$wrapperName}
          itemCount={$wrapperItems.length}
          canEdit={$wrapperPermissions.canEdit}
          canDelete={$wrapperPermissions.canDelete}
        />
      {/if}
    </Page.Flex>
  </Page.Header>
  <Page.Main>
    <Table.Root {viewModel} resourceName="integration">
      <Table.Group></Table.Group>
    </Table.Root>
    <SyncHistoryDialog
      knowledge={selectedIntegrationForSyncHistory}
      bind:open={showSyncHistoryDialog}
    ></SyncHistoryDialog>
  </Page.Main>
</Page.Root>
