<script lang="ts">
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconFileAudio } from "@eneo/icons/file-audio";
  import { IconFileImage } from "@eneo/icons/file-image";
  import { IconFileText } from "@eneo/icons/file-text";
  import { IconMicrophone } from "@eneo/icons/microphone";
  import { m } from "$lib/paraglide/messages";
  import type { App } from "@eneo/eneo-js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Select as SelectPrimitive } from "bits-ui";
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
</script>

<Select.Root type="single" {value} onValueChange={(next) => (value = next as InputType)}>
  <SelectPrimitive.Trigger>
    {#snippet child({ props })}
      <button
        {...props}
        {...aria}
        class="border-default hover:bg-hover-dimmer flex h-16 items-center justify-between border-b px-4"
      >
        {#if value}
          <div class="flex items-center gap-3">
            <svelte:component this={inputTypes[value].icon}></svelte:component>
            <span>{inputTypes[value].label}</span>
          </div>
        {:else}
          {m.nothing_selected()}
        {/if}
        <IconChevronDown />
      </button>
    {/snippet}
  </SelectPrimitive.Trigger>
  <Select.Content>
    {#each Object.entries(groupedTypes) as [type, inputOptions] (type)}
      <Select.Group>
        <Select.GroupHeading class="capitalize">{type}</Select.GroupHeading>
        {#each inputOptions as inputOption (inputOption)}
          {@const { icon, label } = inputTypes[inputOption]}
          <Select.Item value={inputOption} {label} class="min-h-10 gap-3">
            <svelte:component this={icon}></svelte:component>
            <span>{label}</span>
          </Select.Item>
        {/each}
      </Select.Group>
    {/each}
  </Select.Content>
</Select.Root>
