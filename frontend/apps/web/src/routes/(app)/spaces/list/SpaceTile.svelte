<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { SpaceSparse } from "@intric/intric-js";
  import { dynamicColour } from "$lib/core/colours";
  import { getAppContext } from "$lib/core/AppContext";

  export let space: SpaceSparse;

  const { environment } = getAppContext();

  // Generate icon URL from icon_id
  $: iconUrl = space.icon_id
    ? `${environment.baseUrl}/api/v1/icons/${space.icon_id}/`
    : null;
</script>

<a
  aria-label={space.name}
  href="/spaces/{space.id}"
  {...dynamicColour({ basedOn: space.id })}
  class="group border-dynamic-default bg-dynamic-dimmer text-dynamic-stronger hover:bg-dynamic-default hover:text-on-fill relative flex aspect-square flex-col items-start gap-4 border-t p-4 pt-2"
>
  <h2 class="line-clamp-3 pt-1 font-mono text-sm">
    {space.name}
  </h2>

  <div class="pointer-events-none absolute inset-0 flex items-center justify-center">
    {#if iconUrl}
      <div class="flex aspect-square h-20 items-center justify-center overflow-hidden rounded-xl">
        <img src={iconUrl} alt={space.name} class="h-full w-full object-cover" />
      </div>
    {:else}
      <span
        class="bg-dynamic-default text-on-fill group-hover:border-on-fill flex aspect-square h-20 items-center justify-center rounded-xl border border-transparent font-sans text-[3rem]"
        >{[...space.name][0].toUpperCase()}</span
      >
    {/if}
  </div>

  <div class="pointer-events-none absolute inset-0 flex items-center justify-center"></div>
</a>
