<script lang="ts">
  import type { ServiceSparse } from "@eneo/eneo-js";
  import { IconService } from "@eneo/icons/service";
  import ResourceTile from "$lib/features/spaces/components/ResourceTile.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { localizeHref } from "$lib/paraglide/runtime";
  import ServiceActions from "./ServiceActions.svelte";

  let { service }: { service: ServiceSparse } = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();
</script>

<ResourceTile
  href={localizeHref(`/spaces/${$currentSpace.routeId}/services/${service.id}?tab=playground`)}
  name={service.name}
  id={service.id}
>
  {#snippet icon()}
    <IconService size="lg" />
  {/snippet}
  {#snippet actions()}
    <ServiceActions {service} />
  {/snippet}
</ResourceTile>
