<script lang="ts">
  import { goto } from "$app/navigation";
  import { groupIntegrationSources } from "$lib/features/integrations/sources";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import SourcePage from "../source/SourcePage.svelte";

  let { data } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  // Re-read the item from the space so renames and finished syncs show without a reload.
  let item = $derived(
    $currentSpace.knowledge.integrationKnowledge.find(
      (candidate) => candidate.id === data.knowledgeId && candidate.space_id === $currentSpace.id
    ) ?? null
  );
  let source = $derived(item ? groupIntegrationSources([item])[0] : null);

  // The item was deleted from its actions menu: this page has nothing left to show.
  $effect(() => {
    if (!item && $currentSpace.id === data.currentSpace.id) {
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic space route
      void goto(`/spaces/${$currentSpace.routeId}/knowledge?tab=integrations`);
    }
  });
</script>

{#if source}
  {#key source.id}
    <SourcePage {source} />
  {/key}
{/if}
