<script lang="ts">
  import { IconCheck } from "@intric/icons/check";
  import { IconChevronUpDown } from "@intric/icons/chevron-up-down";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { createSelect } from "@melt-ui/svelte";
  import SpaceChip from "$lib/features/spaces/components/SpaceChip.svelte";
  import { goto } from "$app/navigation";
  import { fly } from "svelte/transition";
  import { quadInOut } from "svelte/easing";
  import { formatEmojiTitle } from "$lib/core/formatting/formatEmojiTitle";
  import { getChatService } from "../../ChatService.svelte";
  import type { AssistantSparse, GroupChatSparse } from "@intric/intric-js";
  import { getChatQueryParams } from "../../getChatQueryParams";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const chat = getChatService();

  const {
    elements: { trigger, menu, option },
    states: { selected }
  } = createSelect<GroupChatSparse | AssistantSparse>({
    positioning: {
      placement: "bottom-start",
      fitViewport: true
    },
    defaultSelected: { value: $state.snapshot(chat.partner) },
    onSelectedChange: ({ next }) => {
      if (next) {
        goto(
          `/spaces/${$currentSpace.routeId}/chat/?${getChatQueryParams({ chatPartner: next.value })}`
        );
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
  <span class="truncate">{chat.partner.name}</span>
  <!-- translate-y to make it look on the same line as the chevron in the space selector -->
  <IconChevronUpDown
    class="text-secondary group-hover:text-primary min-w-6 translate-y-[0.05rem]"
  />
</button>

<div
  class="border-default bg-primary z-10 flex min-w-[24vw] flex-col overflow-y-auto rounded-lg border shadow-xl"
  {...$menu}
  use:menu
>
  <div
    class="bg-frosted-glass-secondary border-default sticky top-0 border-b px-4 py-2 pr-12 font-mono text-sm"
  >
    {m.select_an_assistant()}
  </div>
  {#each $currentSpace.applications.chat as partner (partner.id)}
    <div
      class="border-default hover:bg-hover-default flex min-h-16 items-center gap-4 border-b px-4 hover:cursor-pointer"
      {...$option({ value: partner, label: partner.name, disabled: false })}
      use:option
    >
      <SpaceChip space={{ ...partner, personal: false }}></SpaceChip>
      {formatEmojiTitle(partner.name)}
      <div class="flex-grow"></div>
      <div class="check {$selected?.value.id === partner.id ? 'block' : 'hidden'}">
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
