<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { page } from "$app/stores";
  import { getAppContext } from "$lib/core/AppContext";
  import { dynamicColour } from "$lib/core/colours";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Sheet from "$lib/components/ui/sheet/index.js";
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

  // Narrow viewports collapse the space navigation into a Sheet; navigating
  // anywhere closes it again.
  let mobileNavOpen = false;
  $: if ($page.url.pathname) mobileNavOpen = false;
</script>

<svelte:head>
  <title>Eneo.ai – {data.currentSpace.personal ? m.personal() : data.currentSpace.name}</title>
</svelte:head>

<div
  {...dynamicColour({ basedOn: $currentSpace.personal ? user.id : $currentSpace.id })}
  class="absolute inset-0 flex flex-grow justify-stretch"
>
  <div
    class="border-default flex flex-col border-r-[0.5px] max-md:hidden md:max-w-[17rem] md:min-w-[17rem]"
  >
    <SpaceSelector></SpaceSelector>
    <SpaceMenu></SpaceMenu>
  </div>

  <!-- Below md the sidebar collapses to a slim rail; the hamburger opens the
       same navigation in a Sheet so pages get (almost) the full viewport. -->
  <div
    class="border-default flex w-12 shrink-0 flex-col items-center border-r-[0.5px] pt-2 md:hidden"
  >
    <Button
      variant="ghost"
      size="icon"
      aria-label={m.space_nav_open()}
      onclick={() => (mobileNavOpen = true)}
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 20 20"
        fill="currentColor"
        class="size-5"
        aria-hidden="true"
      >
        <path
          fill-rule="evenodd"
          d="M2 4.75A.75.75 0 0 1 2.75 4h14.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 4.75Zm0 5.25a.75.75 0 0 1 .75-.75h14.5a.75.75 0 0 1 0 1.5H2.75A.75.75 0 0 1 2 10Zm0 5.25a.75.75 0 0 1 .75-.75h14.5a.75.75 0 0 1 0 1.5H2.75a.75.75 0 0 1-.75-.75Z"
          clip-rule="evenodd"
        />
      </svg>
    </Button>
  </div>

  <Sheet.Root bind:open={mobileNavOpen}>
    <Sheet.Content
      side="left"
      class="flex w-[17rem] flex-col gap-0 p-0"
      {...dynamicColour({ basedOn: $currentSpace.personal ? user.id : $currentSpace.id })}
    >
      <Sheet.Title class="sr-only">{m.space_nav_title()}</Sheet.Title>
      <SpaceSelector></SpaceSelector>
      <SpaceMenu></SpaceMenu>
    </Sheet.Content>
  </Sheet.Root>

  <slot />
  <div
    class="pointer-events-none absolute inset-0 -z-0 flex flex-grow shadow-xl left-12 md:left-[17rem]"
  ></div>
</div>
