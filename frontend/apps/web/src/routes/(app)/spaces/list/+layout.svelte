<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { page } from "$app/stores";
  import { Navigation } from "$lib/components/layout";
  import SpaceSelector from "$lib/features/spaces/components/SpaceSelector.svelte";
  import { IconSquares } from "@intric/icons/squares";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";

  $: section = $page.url.pathname.split("/")[3] ?? "list";
</script>

<svelte:head>
  <title>Eneo.ai – {m.spaces()}</title>
</svelte:head>

<div data-dynamic-colour="blue" class="absolute inset-0 flex flex-grow justify-stretch">
  <div class="border-default flex flex-col border-r-[0.5px] md:max-w-[17rem] md:min-w-[17rem]">
    <SpaceSelector showSelectPrompt={true}></SpaceSelector>
    <Navigation.Menu>
      <Navigation.Link
        href={localizeHref("/spaces/list")}
        isActive={section === "list"}
        icon={IconSquares}
        label={m.your_spaces()}
      />
    </Navigation.Menu>
  </div>
  <slot />
  <div
    class="pointer-events-none absolute inset-0 -z-0 flex flex-grow shadow-xl md:left-[17rem]"
  ></div>
</div>
