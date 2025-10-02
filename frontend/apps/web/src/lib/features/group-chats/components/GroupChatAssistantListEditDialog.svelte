<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconCog } from "@intric/icons/cog";
  import type { GroupChat } from "@intric/intric-js";
  import { Button, Dialog, Input } from "@intric/ui";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  type AssistantTool = GroupChat["tools"]["assistants"][number];
  type Props = {
    updateAssistant: (assistant: AssistantTool) => void;
    assistant: AssistantTool;
  };

  const { assistant, updateAssistant }: Props = $props();

  let descriptionProxy = $derived.by(() => {
    let value = $state(assistant.user_description ?? "");
    return { value };
  });

  let isOpen = writable(false);
</script>

<Dialog.Root openController={isOpen}>
  <Dialog.Trigger let:trigger asFragment>
    <Button variant="outlined" is={trigger} padding="icon"><IconCog></IconCog></Button>
  </Dialog.Trigger>

  <Dialog.Content width="medium">
    <Dialog.Title>{m.edit_assistant_description()}</Dialog.Title>
    <Dialog.Section scrollable={false}>
      <Input.Text
        class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
        inputClass="pointer-events-none text-secondary"
        value={assistant.handle}
        disabled
      >
        {m.assistant()}
      </Input.Text>
      <Input.TextArea
        class=" border-default hover:bg-hover-dimmer px-4 py-4"
        label={m.description()}
        description={m.will_help_determine_assistant()}
        bind:value={descriptionProxy.value}
        placeholder={assistant?.default_description}
      ></Input.TextArea>
    </Dialog.Section>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button
        variant="primary"
        onclick={() => {
          const user_description =
            descriptionProxy.value.trim() === "" ? null : descriptionProxy.value;
          if (!user_description && !assistant.default_description) {
            alert(m.description_required_for_assistant());
            return;
          }
          updateAssistant({ ...assistant, user_description });
          $isOpen = false;
        }}>{m.accept_changes()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
