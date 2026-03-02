<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { initFlowsManager } from "$lib/features/flows/FlowsManager";
  import { m } from "$lib/paraglide/messages";
  import FlowsTable from "./FlowsTable.svelte";
  import CreateFlowDialog from "./CreateFlowDialog.svelte";

  export let data;

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const {
    state: { flows }
  } = initFlowsManager({
    flows: data.flows,
    spaceId: $currentSpace.id,
    intric: data.intric
  });
</script>

<svelte:head>
  <title>Eneo.ai – {$currentSpace.personal ? m.personal() : $currentSpace.name} – {m.flows()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.flows()}></Page.Title>
    {#if $currentSpace.hasPermission("create", "app")}
      <CreateFlowDialog />
    {/if}
  </Page.Header>
  <Page.Main>
    <FlowsTable flows={$flows} />
  </Page.Main>
</Page.Root>
