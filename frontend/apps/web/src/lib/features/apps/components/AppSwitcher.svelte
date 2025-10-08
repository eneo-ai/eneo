<script lang="ts">
  import { IconCheck } from "@intric/icons/check";
  import { IconChevronUpDown } from "@intric/icons/chevron-up-down";
  import { goto } from "$app/navigation";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { createSelect } from "@melt-ui/svelte";
  import { fly } from "svelte/transition";
  import { quadInOut } from "svelte/easing";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import SpaceChip from "$lib/features/spaces/components/SpaceChip.svelte";
  import { m } from "$lib/paraglide/messages";

  export let currentApp: { id: string; name: string };

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const {
    elements: { trigger, menu, option },
    helpers: { isSelected }
  } = createSelect<{ id: string }>({
    positioning: {
      placement: "bottom-start",
      fitViewport: true
    },
    defaultSelected: { value: { id: currentApp.id } },
    onSelectedChange: ({ next }) => {
      if (next) {
        goto(`/spaces/${$currentSpace.routeId}/apps/${next.value.id}`);
      }
      return next;
    }
  });
</script>

<button
  {...$trigger}
  use:trigger
  in:fly|global={{ x: -5, duration: parent ? 300 : 0, easing: quadInOut, opacity: 0.3 }}
  class="group text-primary hover:border-dimmer hover:bg-hover-default flex max-w-[calc(100%_-_1rem)] items-center justify-between gap-2 overflow-hidden rounded-lg border border-transparent py-0.5 pr-1 pl-2 text-[1.4rem] leading-normal font-extrabold"
>
  <span class="truncate">{currentApp.name}</span>
  <!-- translate-y to make it look on the same line as the chevron in the space selector -->
  <IconChevronUpDown
    class="text-secondary group-hover:text-primary h-6 w-6 min-w-6 translate-y-[0.05rem]"
  ></IconChevronUpDown>
</button>

<div
  class="border-default bg-primary z-10 flex min-w-[24vw] flex-col overflow-y-auto rounded-lg border shadow-xl"
  {...$menu}
  use:menu
>
  <div
    class="bg-frosted-glass-secondary border-default sticky top-0 border-b px-4 py-2 pr-12 font-mono text-sm"
  >
    {m.select_an_app()}
  </div>
  {#each $currentSpace.applications.apps as app (app.id)}
    <div
      class="border-default hover:bg-hover-default flex min-h-16 items-center gap-4 border-b px-4 hover:cursor-pointer"
      {...$option({ value: { id: app.id } })}
      use:option
    >
      <SpaceChip space={{ ...app, personal: false }}></SpaceChip>
      {formatEmojiTitle(app.name)}
      <div class="flex-grow"></div>
      <div class="check {$isSelected({ id: app.id }) ? 'block' : 'hidden'}">
        <IconCheck class="text-positive-stronger !size-8"></IconCheck>
      </div>
    </div>
  {/each}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";
  div[data-highlighted] {
    @apply bg-hover-default;
  }

  /* div[data-selected] { } */

  div[data-disabled] {
    @apply opacity-30 hover:bg-transparent;
  }
</style>
