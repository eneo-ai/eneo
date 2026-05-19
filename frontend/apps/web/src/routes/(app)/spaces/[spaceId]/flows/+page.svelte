<script lang="ts">
  import { untrack } from "svelte";
  import type { FlowSparse, Intric } from "@intric/intric-js";
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
    data: { flows: FlowSparse[]; intric: Intric };
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
      intric: data.intric
    })
  );

  const countLabel = $derived.by(() => {
    const count = $flows.length;
    if (count === 0) return m.flow_list_count_zero();
    if (count === 1) return m.flow_list_count_singular();
    return m.flow_list_count_plural({ count: String(count) });
  });
</script>

<svelte:head>
  <title>Eneo.ai – {$currentSpace.personal ? m.personal() : $currentSpace.name} – {m.flows()}</title
  >
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.flows()}></Page.Title>
    {#if user.hasPermission("flows_manage")}
      <div class="flex items-center gap-2">
        <FlowPackageImportDialog
          intric={data.intric}
          spaceId={$currentSpace.id}
          spaceRouteId={$currentSpace.routeId}
        />
        <CreateFlowDialog />
      </div>
    {/if}
  </Page.Header>
  <Page.Main>
    <div class="mx-auto flex w-full max-w-[1400px] flex-col gap-4 px-3 py-4 sm:px-6 sm:py-6">
      <p class="text-muted text-xs font-medium tracking-wide uppercase" aria-live="polite">
        {countLabel}
      </p>
      <FlowsTable flows={$flows} />
    </div>
  </Page.Main>
</Page.Root>
