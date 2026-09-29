<script lang="ts">
  import type { AppSparse } from "@eneo/eneo-js";
  import AppIcon from "$lib/features/apps/components/AppIcon.svelte";
  import ResourceTile from "$lib/features/spaces/components/ResourceTile.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { localizeHref } from "$lib/paraglide/runtime";
  import AppActions from "./AppActions.svelte";

  let { app }: { app: AppSparse } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();
</script>

<ResourceTile
  href={localizeHref(`/spaces/${$currentSpace.routeId}/apps/${app.id}`)}
  name={app.name}
  id={app.id}
>
  {#snippet icon()}
    <AppIcon {app} />
  {/snippet}
  {#snippet actions()}
    <AppActions {app} />
  {/snippet}
</ResourceTile>
