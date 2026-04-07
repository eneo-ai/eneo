<script lang="ts">
  import { setAvailableIntegrations } from "$lib/features/integrations/AvailableIntegrations.js";

  let { data, children } = $props();

  // Initial call creates the Svelte context store (must run synchronously at init)
  setAvailableIntegrations(
    data.availableIntegrations.filter((i) => i.integration_type === "sharepoint")
  );

  // Update store reactively when space (and thus data) changes
  $effect(() => {
    setAvailableIntegrations(
      data.availableIntegrations.filter((i) => i.integration_type === "sharepoint")
    );
  });
</script>

{@render children?.()}
