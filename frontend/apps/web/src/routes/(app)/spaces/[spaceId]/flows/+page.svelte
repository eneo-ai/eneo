<script lang="ts">
  import { untrack } from "svelte";
  import type { FlowSparse, Eneo } from "@eneo/eneo-js";
  import { Page } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { initFlowsManager } from "$lib/features/flows/FlowsManager";
  import { getAppContext } from "$lib/core/AppContext";
  import { m } from "$lib/paraglide/messages";
  import FlowsTable from "./FlowsTable.svelte";
  import CreateFlowDialog from "./CreateFlowDialog.svelte";
  import FlowPackageImportDialog from "$lib/features/flows/components/FlowPackageImportDialog.svelte";

  let {
    data
  }: {
    data: { flows: FlowSparse[]; eneo: Eneo };
  } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();
  const { user } = getAppContext();

  // Flows manager consumes the initial data payload once; downstream reactivity lives
  // inside its own stores, so we untrack to silence the initial-reference warning.
  const {
    state: { flows }
  } = untrack(() =>
    initFlowsManager({
      flows: data.flows,
      spaceId: $currentSpace.id,
      eneo: data.eneo
    })
  );

  const canManage = user.hasPermission("flows_manage");
  let createOpen = $state(false);
</script>

<svelte:head>
  <title>Eneo.ai – {$currentSpace.personal ? m.personal() : $currentSpace.name} – {m.flows()}</title
  >
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.flows()} description={m.flow_list_page_description()}></Page.Title>
    {#if canManage}
      <!-- The header is one fixed row: the actions keep their size and the
           title gives way, rather than the primary action sliding off a phone. -->
      <div class="flex shrink-0 items-center gap-2">
        <FlowPackageImportDialog
          eneo={data.eneo}
          spaceId={$currentSpace.id}
          spaceRouteId={$currentSpace.routeId}
        />
        <CreateFlowDialog bind:open={createOpen} />
      </div>
    {/if}
  </Page.Header>
  <Page.Main>
    <div class="mx-auto flex w-full max-w-[66.25rem] flex-col gap-4 px-3 py-4 sm:px-6 sm:py-6">
      <FlowsTable flows={$flows} canCreate={canManage} oncreate={() => (createOpen = true)} />
    </div>
  </Page.Main>
</Page.Root>
