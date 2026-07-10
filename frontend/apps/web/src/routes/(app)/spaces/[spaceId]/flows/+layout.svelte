<script lang="ts">
  import { initFlowUserMode } from "$lib/features/flows/FlowUserMode";

  let { children } = $props();

  // Single owner of the Enkel/Avancerad mode context for every flows route
  // (list, detail builder, AI builder). Child components read it via
  // getFlowUserMode(); no route may re-initialize it.
  initFlowUserMode();
</script>

{@render children()}
