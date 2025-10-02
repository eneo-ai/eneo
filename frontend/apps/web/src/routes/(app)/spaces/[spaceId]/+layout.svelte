<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getAppContext } from "$lib/core/AppContext";
  import { dynamicColour } from "$lib/core/colours";
  import SpaceSelector from "$lib/features/spaces/components/SpaceSelector.svelte";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager.js";
  import SpaceMenu from "./SpaceMenu.svelte";
  import { m } from "$lib/paraglide/messages";

  export let data;

  // Hint: SpacesManager will listen to route / spaceId changes
  const {
    state: { currentSpace },
    watchPageData
  } = getSpacesManager();

  const { user } = getAppContext();

  $: watchPageData(data);
</script>

<svelte:head>
  <title>Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name}</title>
</svelte:head>

<div
  {...dynamicColour({ basedOn: $currentSpace.personal ? user.id : $currentSpace.id })}
  class="absolute inset-0 flex flex-grow justify-stretch"
>
  <div class="border-default flex flex-col border-r-[0.5px] md:max-w-[17rem] md:min-w-[17rem]">
    <SpaceSelector></SpaceSelector>
    <SpaceMenu></SpaceMenu>
  </div>
  <slot />
  <div
    class="pointer-events-none absolute inset-0 -z-0 flex flex-grow shadow-xl md:left-[17rem]"
  ></div>
</div>
