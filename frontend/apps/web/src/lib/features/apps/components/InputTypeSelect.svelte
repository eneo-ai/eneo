<script lang="ts" module>
  import type { App } from "@eneo/eneo-js";

  export type InputType = App["input_fields"][number]["type"];
</script>

<script lang="ts">
  import type { Icon } from "@eneo/icons";
  import { IconChevronDown } from "@eneo/icons/chevron-down";
  import { IconEdit } from "@eneo/icons/edit";
  import { IconFileAudio } from "@eneo/icons/file-audio";
  import { IconFileImage } from "@eneo/icons/file-image";
  import { IconFileText } from "@eneo/icons/file-text";
  import { IconMicrophone } from "@eneo/icons/microphone";
  import { Select as SelectPrimitive } from "bits-ui";
  import * as Select from "$lib/components/ui/select/index.js";
  import { m } from "$lib/paraglide/messages";

  let { value = $bindable(), aria }: { value: InputType; aria?: AriaProps } = $props();

  const inputTypes: Record<InputType, { icon: Icon; label: string }> = {
    "text-upload": { icon: IconFileText, label: m.upload_text_document() },
    "text-field": { icon: IconEdit, label: m.enter_text_directly() },
    "audio-upload": { icon: IconFileAudio, label: m.upload_audio_file() },
    "audio-recorder": { icon: IconMicrophone, label: m.record_microphone_audio() },
    "image-upload": { icon: IconFileImage, label: m.upload_image_file() }
  };

  const groups: { heading: string; options: InputType[] }[] = [
    { heading: m.text(), options: ["text-field", "text-upload"] },
    { heading: m.audio(), options: ["audio-recorder", "audio-upload"] },
    { heading: m.image(), options: ["image-upload"] }
  ];
</script>

<Select.Root
  type="single"
  {value}
  onValueChange={(next) => {
    if (next) value = next as InputType;
  }}
>
  <SelectPrimitive.Trigger>
    {#snippet child({ props })}
      <button
        {...props}
        {...aria}
        class="border-default hover:bg-hover-dimmer flex h-16 w-full items-center justify-between border-b px-4"
      >
        {#if value}
          {@const { icon: SelectedIcon, label } = inputTypes[value]}
          <div class="flex items-center gap-3">
            <SelectedIcon />
            <span>{label}</span>
          </div>
        {:else}
          {m.nothing_selected()}
        {/if}
        <IconChevronDown />
      </button>
    {/snippet}
  </SelectPrimitive.Trigger>
  <Select.Content>
    {#each groups as { heading, options } (heading)}
      <Select.Group>
        <Select.GroupHeading class="capitalize">{heading}</Select.GroupHeading>
        {#each options as option (option)}
          {@const { icon: OptionIcon, label } = inputTypes[option]}
          <Select.Item value={option} {label} class="min-h-10 gap-3">
            <OptionIcon />
            <span>{label}</span>
          </Select.Item>
        {/each}
      </Select.Group>
    {/each}
  </Select.Content>
</Select.Root>
