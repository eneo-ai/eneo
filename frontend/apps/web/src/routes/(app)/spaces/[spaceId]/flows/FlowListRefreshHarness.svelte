<script lang="ts">
  import type { Eneo, FlowSparse } from "@eneo/eneo-js";
  import { untrack } from "svelte";
  import { initFlowsManager } from "$lib/features/flows/FlowsManager";
  import FlowsTable from "./FlowsTable.svelte";

  let data: { eneo: Eneo; initial: FlowSparse[] } = $props();
  export const manager = untrack(() =>
    initFlowsManager({ eneo: data.eneo, flows: data.initial, spaceId: "space-1" })
  );
  const { flows, refreshError, refreshing } = manager.state;
</script>

<FlowsTable
  flows={$flows}
  drafts={[]}
  refreshFailed={$refreshError !== null}
  refreshing={$refreshing}
  onretry={manager.refreshFlows}
/>
