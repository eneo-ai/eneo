<script lang="ts">
  import { goto } from "$app/navigation";
  import ResourceSwitcher from "$lib/components/ResourceSwitcher.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import SpaceChip from "$lib/features/spaces/components/SpaceChip.svelte";
  import { m } from "$lib/paraglide/messages";

  let { currentApp }: { currentApp: { id: string; name: string } } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();
</script>

<ResourceSwitcher
  items={$currentSpace.applications.apps}
  current={currentApp}
  heading={m.select_an_app()}
  onSelect={(app) => {
    // eslint-disable-next-line svelte/no-navigation-without-resolve -- dynamic URL with space and app ids
    goto(`/spaces/${$currentSpace.routeId}/apps/${app.id}`);
  }}
>
  {#snippet itemIcon(app)}
    <SpaceChip space={{ ...app, personal: false }} />
  {/snippet}
</ResourceSwitcher>
