<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconPlus } from "@intric/icons/plus";
  import type { GroupChat } from "@intric/intric-js";
  import { Button, Dialog, Input, Select } from "@intric/ui";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";

  type AssistantTool = GroupChat["tools"]["assistants"][number];
  type Props = {
    addAssistantToGroup: (assistant: AssistantTool) => void;
    availableAssistants: AssistantTool[];
  };

  const { addAssistantToGroup, availableAssistants }: Props = $props();

  let selectedAssistant = $state<AssistantTool | undefined>();
  let user_description = $state("");
  let isOpen = writable(false);
</script>

<Dialog.Root openController={isOpen}>
  <Dialog.Trigger let:trigger asFragment>
    <Button variant="outlined" is={trigger} class="h-12"><IconPlus></IconPlus>{m.add_assistant()}</Button>
  </Dialog.Trigger>

  <Dialog.Content width="medium">
    <Dialog.Title>{m.add_new_assistant_to_group()}</Dialog.Title>
    <Dialog.Section scrollable={false}>
      <Select.Simple
        class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
        options={availableAssistants.map((assistant) => {
          return {
            label: assistant.handle,
            value: assistant
          };
        })}
        bind:value={selectedAssistant}>{m.choose_an_assistant_to_add()}</Select.Simple
      >
      <Input.TextArea
        class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
        bind:value={user_description}
        placeholder={selectedAssistant?.default_description ?? m.enter_a_description()}
        label={m.describe_responsibilities()}
        description={m.add_description_to_help_determine()}
      ></Input.TextArea>
    </Dialog.Section>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button
        variant="primary"
        disabled={!selectedAssistant}
        onclick={() => {
          if (selectedAssistant) {
            if (!user_description && selectedAssistant.default_description === null) {
              alert(m.description_required_to_add_assistant());
              return;
            }
            addAssistantToGroup({ ...selectedAssistant, user_description });
            user_description = "";
            $isOpen = false;
          }
        }}>{m.add_to_group()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
