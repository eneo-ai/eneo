<script lang="ts">
  import { setAvailableIntegrations } from "$lib/features/integrations/AvailableIntegrations.js";

  let { data, children } = $props();

  // Filter out integrations that are not yet ready (e.g., Confluence)
  const readyIntegrations = data.availableIntegrations.filter(
    (i) => i.integration_type === "sharepoint"
  );
  setAvailableIntegrations(readyIntegrations);
</script>

{@render children?.()}
