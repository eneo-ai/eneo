<script lang="ts">
  import { goto } from "$app/navigation";
  import { groupIntegrationSources } from "$lib/features/integrations/sources";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import SourcePage from "../../source/SourcePage.svelte";

  let { data } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();

  // Re-read the items from the space so renames, syncs and deletions show without a reload.
  let items = $derived(
    $currentSpace.knowledge.integrationKnowledge.filter(
      (item) => item.wrapper_id === data.wrapperId && item.space_id === $currentSpace.id
    )
  );
  let source = $derived(items.length > 0 ? groupIntegrationSources(items)[0] : null);

  let isAdmin = $derived(
    data.user?.roles?.some((role: { permissions?: string[] }) =>
      role.permissions?.includes("admin")
    ) ?? false
  );

  // The wrapper was deleted from its actions menu: this page has nothing left to show.
  $effect(() => {
    if (items.length === 0 && $currentSpace.id === data.currentSpace.id) {
      // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic space route
      void goto(`/spaces/${$currentSpace.routeId}/knowledge?tab=integrations`);
    }
  });
</script>

{#if source}
  <SourcePage {source} {isAdmin} />
{/if}
