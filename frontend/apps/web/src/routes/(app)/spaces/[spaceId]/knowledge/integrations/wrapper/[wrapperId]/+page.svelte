<script lang="ts">
  import { goto } from "$app/navigation";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import { groupIntegrationSources } from "$lib/features/integrations/sources";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import SourcePage from "../../source/SourcePage.svelte";

  let { data } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  // Re-read the items from the space so renames, syncs and deletions show without a reload.
  // The space store can still predate a fresh import; the loaded items stand in until then.
  let inSpace = $derived(
    $currentSpace.knowledge.integrationKnowledge.filter(
      (item: IntegrationKnowledge) =>
        item.wrapper_id === data.wrapperId && item.space_id === $currentSpace.id
    )
  );
  let items = $derived(inSpace.length > 0 ? inSpace : (data.items as IntegrationKnowledge[]));
  let source = $derived(items.length > 0 ? groupIntegrationSources(items)[0] : null);

  // The wrapper was deleted from its actions menu: this page has nothing left to show.
  // Only a disappearance counts, never a store that has not seen the wrapper yet.
  let seenWrapperId: string | null = null;
  $effect(() => {
    if (inSpace.length > 0) {
      seenWrapperId = data.wrapperId;
    } else if (seenWrapperId === data.wrapperId && $currentSpace.id === data.currentSpace.id) {
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic space route
      void goto(`/spaces/${$currentSpace.routeId}/knowledge?tab=integrations`);
    }
  });
</script>

{#if source}
  <!-- Another wrapper is another source: start its page fresh. -->
  {#key data.wrapperId}
    <SourcePage {source} />
  {/key}
{/if}
