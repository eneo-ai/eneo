<script lang="ts">
  import { IconCheck } from "@intric/icons/check";
  import { IconChevronDown } from "@intric/icons/chevron-down";
  import { IconEdit } from "@intric/icons/edit";
  import { IconFileAudio } from "@intric/icons/file-audio";
  import { IconFileImage } from "@intric/icons/file-image";
  import { IconFileText } from "@intric/icons/file-text";
  import { IconMicrophone } from "@intric/icons/microphone";
  import { m } from "$lib/paraglide/messages";
  import type { App } from "@intric/intric-js";
  import { createSelect } from "@melt-ui/svelte";
  import type { ComponentType } from "svelte";

  type InputType = App["input_fields"][number]["type"];

  export let value: InputType;
  export let aria: AriaProps;

  const inputTypes: Record<InputType, { icon: ComponentType; label: string }> = {
    "text-upload": { icon: IconFileText, label: m.upload_text_document() },
    "text-field": { icon: IconEdit, label: m.enter_text_directly() },
    "audio-upload": { icon: IconFileAudio, label: m.upload_audio_file() },
    "audio-recorder": { icon: IconMicrophone, label: m.record_microphone_audio() },
    "image-upload": { icon: IconFileImage, label: m.upload_image_file() }
  };

  const groupedTypes: Record<string, Array<InputType>> = {
    text: ["text-field", "text-upload"],
    audio: ["audio-recorder", "audio-upload"],
    image: ["image-upload"]
  };

  const {
    elements: { trigger, menu, option, group, groupLabel },
    states: { selected },
    helpers: { isSelected }
  } = createSelect<InputType>({
    positioning: {
      placement: "bottom",
      fitViewport: true,
      sameWidth: true
    },
    defaultSelected: { value },
    portal: null,
    onSelectedChange: ({ next }) => {
      value = next?.value ?? value;
      return next;
    }
  });

  function watchChanges(value: InputType) {
    if ($selected?.value !== value) {
      $selected = { value };
    }
  }
  // Watch outside changes
  $: watchChanges(value);
</script>

<button
  {...$trigger}
  {...aria}
  use:trigger
  class="border-default hover:bg-hover-dimmer flex h-16 items-center justify-between border-b px-4"
>
  {#if $selected}
    <div class="flex items-center gap-3">
      <svelte:component this={inputTypes[$selected.value].icon}></svelte:component>
      <span>{inputTypes[$selected.value].label}</span>
    </div>
  {:else}
    {m.nothing_selected()}
  {/if}
  <IconChevronDown />
</button>

<div
  class="border-stronger bg-primary z-20 flex flex-col overflow-y-auto rounded-lg border shadow-xl"
  {...$menu}
  use:menu
>
  {#each Object.entries(groupedTypes) as [type, inputOptions] (type)}
    <div {...$group(type)} use:group class="">
      <div
        class="bg-frosted-glass-secondary border-default flex items-center gap-3 border-b px-4 py-2 font-mono text-sm capitalize"
        {...$groupLabel(type)}
        use:groupLabel
      >
        {type}
      </div>
      {#each inputOptions as inputOption (inputOption)}
        {@const { icon, label } = inputTypes[inputOption]}
        <div
          class="border-default hover:bg-hover-default flex min-h-16 items-center justify-between border-b px-4 last-of-type:border-b-0 hover:cursor-pointer"
          {...$option({ value: inputOption })}
          use:option
        >
          <div class="flex items-center gap-3">
            <svelte:component this={icon}></svelte:component>
            <span>{label}</span>
          </div>
          <div class="check {$isSelected(inputOption) ? 'block' : 'hidden'}">
            <IconCheck class="text-positive-default !size-8"></IconCheck>
          </div>
        </div>
      {/each}
    </div>
  {/each}
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";
  div[data-highlighted] {
    @apply bg-hover-default;
  }

  div[data-disabled] {
    @apply opacity-30 hover:bg-transparent;
  }
</style>
