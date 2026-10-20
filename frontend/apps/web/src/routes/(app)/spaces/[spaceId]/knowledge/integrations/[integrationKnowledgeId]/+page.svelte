<script lang="ts">
  import { goto } from "$app/navigation";
  import type { IntegrationKnowledge } from "@eneo/eneo-js";
  import { groupIntegrationSources } from "$lib/features/integrations/sources";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import SourcePage from "../source/SourcePage.svelte";

  let { data } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  // Re-read the item from the space so renames and finished syncs show without a reload.
  // The space store can still predate a fresh import; the loaded item stands in until then.
  let inSpace = $derived(
    $currentSpace.knowledge.integrationKnowledge.find(
      (candidate: IntegrationKnowledge) =>
        candidate.id === data.knowledge.id && candidate.space_id === $currentSpace.id
    ) ?? null
  );
  let item = $derived(inSpace ?? (data.knowledge as IntegrationKnowledge));
  let source = $derived(groupIntegrationSources([item])[0]);

  // The item was deleted from its actions menu: this page has nothing left to show.
  // Only a disappearance counts, never a store that has not seen the item yet.
  let seenInSpaceId: string | null = null;
  $effect(() => {
    if (inSpace) {
      seenInSpaceId = inSpace.id;
    } else if (
      seenInSpaceId === data.knowledge.id &&
      $currentSpace.id === data.knowledge.space_id
    ) {
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic space route
      void goto(`/spaces/${$currentSpace.routeId}/knowledge?tab=integrations`);
    }
  });
</script>

{#key source.id}
  <SourcePage {source} />
{/key}
