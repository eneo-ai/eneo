<script lang="ts">
  import { IconCheck } from "@intric/icons/check";
  import { IconChevronUpDown } from "@intric/icons/chevron-up-down";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { createSelect } from "@melt-ui/svelte";
  import { fly } from "svelte/transition";
  import { quadInOut } from "svelte/easing";
  import ModelNameAndVendor from "$lib/features/ai-models/components/ModelNameAndVendor.svelte";
  import { sortModels } from "$lib/features/ai-models/sortModels";
  import { getChatService } from "../../ChatService.svelte";
  import { m } from "$lib/paraglide/messages";

  const {
    state: { currentSpace },
    updateDefaultAssistant
  } = getSpacesManager();

  const chat = getChatService();

  const {
    elements: { trigger, menu, option },
    helpers: { isSelected }
  } = createSelect<{ id: string }>({
    positioning: {
      placement: "bottom-start",
      fitViewport: true
    },
    defaultSelected: $currentSpace.default_assistant.completion_model
      ? { value: { id: $currentSpace.default_assistant.completion_model.id } }
      : undefined,
    onSelectedChange: ({ next }) => {
      if (next) {
        updateDefaultAssistant({ completionModel: next.value }).then(() => {
          // We also need to make the chat manager aware of the model change
          chat.changeChatPartner($currentSpace.default_assistant);
        });
      }
      return next;
    }
  });
</script>

<button
  {...$trigger}
  use:trigger
  in:fly|global={{ x: -5, duration: parent ? 300 : 0, easing: quadInOut, opacity: 0.3 }}
  class=" group border-default text-primary hover:border-dimmer hover:bg-hover-default flex max-w-[calc(100%_-_4rem)] cursor-pointer items-center justify-between gap-2 overflow-hidden rounded-lg border py-1 pr-1 pl-2 text-[1.4rem] leading-normal font-extrabold"
>
  <span class="truncate text-base font-medium">
    {#if $currentSpace.default_assistant.completion_model}
      {$currentSpace.default_assistant.completion_model.nickname}
    {:else}
      {m.select_a_model()}
    {/if}
  </span>
  <IconChevronUpDown class="text-secondary group-hover:text-primary min-w-6" />
</button>

<div
  class="border-default bg-primary z-10 flex min-w-[24vw] flex-col overflow-y-auto rounded-lg border shadow-xl"
  {...$menu}
  use:menu
>
  <div
    class="bg-frosted-glass-secondary border-default sticky top-0 border-b px-4 py-2 pr-12 font-mono text-sm"
  >
    {m.choose_a_completion_model()}
  </div>
  {#each sortModels($currentSpace.completion_models) as model (model.id)}
    <div
      class="border-default hover:bg-hover-default flex min-h-16 items-center gap-4 border-b px-4 hover:cursor-pointer"
      {...$option({ value: { id: model.id } })}
      use:option
    >
      <ModelNameAndVendor {model}></ModelNameAndVendor>
      <div class="flex-grow"></div>
      <div class="check {$isSelected({ id: model.id }) ? 'block' : 'hidden'}">
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
