<script lang="ts">
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { dynamicColour } from "$lib/core/colours";
  import type { AppSparse } from "@intric/intric-js";
  import AppIcon from "$lib/features/apps/components/AppIcon.svelte";
  import AppActions from "./AppActions.svelte";
  import { localizeHref } from "$lib/paraglide/runtime";

  export let app: AppSparse;

  const {
    state: { currentSpace }
  } = getSpacesManager();
</script>

<a
  aria-label={app.name}
  {...dynamicColour({ basedOn: app.id })}
  href={localizeHref(`/spaces/${$currentSpace.routeId}/apps/${app.id}`)}
  class="group border-dynamic-default bg-dynamic-dimmer text-dynamic-stronger hover:bg-dynamic-default hover:text-on-fill relative flex aspect-square flex-col items-start gap-2 border-t p-2 px-4"
>
  <h2 class="line-clamp-2 pt-1 font-mono text-sm">
    {app.name}
  </h2>

  <div class="hover:text-primary absolute right-2 bottom-2">
    <AppActions {app}></AppActions>
  </div>

  <span
    class="group-hover:text-on-fill pointer-events-none absolute inset-0 flex items-center justify-center font-mono text-[4.5rem]"
  >
    <AppIcon {app}></AppIcon>
  </span>

  <div class="flex-grow"></div>
</a>
