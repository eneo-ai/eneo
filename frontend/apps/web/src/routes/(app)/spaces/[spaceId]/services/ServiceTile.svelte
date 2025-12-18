<script lang="ts">
  import type { ServiceSparse } from "@intric/intric-js";
  import { IconService } from "@intric/icons/service";
  import ServiceActions from "./ServiceActions.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { dynamicColour } from "$lib/core/colours";
  import { localizeHref } from "$lib/paraglide/runtime";

  export let service: ServiceSparse;

  const {
    state: { currentSpace }
  } = getSpacesManager();
</script>

<a
  aria-label={service.name}
  {...dynamicColour({ basedOn: service.id })}
  href={localizeHref(`/spaces/${$currentSpace.routeId}/services/${service.id}?tab=playground`)}
  class="group border-dynamic-default bg-dynamic-dimmer text-dynamic-stronger hover:bg-dynamic-default hover:text-on-fill relative flex aspect-square flex-col items-start gap-2 border-t p-2 px-4"
>
  <h2 class="line-clamp-2 pt-1 font-mono text-sm">
    {service.name}
  </h2>

  <div class="hover:text-primary absolute right-2 bottom-2">
    <ServiceActions {service}></ServiceActions>
  </div>

  <span
    class="group-hover:text-on-fill pointer-events-none absolute inset-0 flex items-center justify-center font-mono text-[4.5rem]"
  >
    <IconService size="lg" />
  </span>

  <div class="flex-grow"></div>
</a>
