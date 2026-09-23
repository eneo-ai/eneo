<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconPlus } from "@eneo/icons/plus";
  import type { GroupChat } from "@eneo/eneo-js";
  import { Button, Dialog, Select } from "@eneo/ui";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";

  type AssistantTool = GroupChat["tools"]["assistants"][number];
  type Props = {
    addAssistantToGroup: (assistant: AssistantTool) => void;
    availableAssistants: AssistantTool[];
  };

  const { addAssistantToGroup, availableAssistants }: Props = $props();
  const uid = $props.id();

  let selectedAssistant = $state<AssistantTool | undefined>();
  let user_description = $state("");
  let isOpen = writable(false);
</script>

<Dialog.Root openController={isOpen}>
  <Dialog.Trigger let:trigger asFragment>
    <Button variant="outlined" is={trigger} class="h-12"
      ><IconPlus></IconPlus>{m.add_assistant()}</Button
    >
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
      <Field.Field class="border-default hover:bg-hover-dimmer border-b px-4 py-4">
        <Field.Label for={`${uid}-user-description`}>{m.describe_responsibilities()}</Field.Label>
        <Textarea
          id={`${uid}-user-description`}
          bind:value={user_description}
          rows={4}
          placeholder={selectedAssistant?.default_description ?? m.enter_a_description()}
          aria-describedby={`${uid}-user-description-description`}
        />
        <Field.Description id={`${uid}-user-description-description`}>
          {m.add_description_to_help_determine()}
        </Field.Description>
      </Field.Field>
    </Dialog.Section>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button
        variant="primary"
        disabled={!selectedAssistant}
        onclick={() => {
          if (selectedAssistant) {
            if (!user_description && selectedAssistant.default_description === null) {
              toast.warning(m.description_required_to_add_assistant());
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
