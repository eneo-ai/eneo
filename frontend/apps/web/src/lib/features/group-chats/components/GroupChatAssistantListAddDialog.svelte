<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconPlus } from "@eneo/icons/plus";
  import type { GroupChat } from "@eneo/eneo-js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
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
  let isOpen = $state(false);

  const selectedHandle = $derived(
    availableAssistants.find(({ id }) => id === selectedAssistant?.id)?.handle
  );
</script>

<Dialog.Root bind:open={isOpen}>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="outline" class="h-12"
        ><IconPlus></IconPlus>{m.add_assistant()}</Button
      >
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.add_new_assistant_to_group()}</Dialog.Title>
    </Dialog.Header>
    <div class={dialogLayout.body}>
      <div class={dialogLayout.section}>
        <Field.Field class="border-default hover:bg-hover-dimmer border-b px-4 py-4">
          <Field.Label for={`${uid}-assistant`}>{m.choose_an_assistant_to_add()}</Field.Label>
          <Select.Root
            type="single"
            value={selectedAssistant?.id ?? ""}
            onValueChange={(id) =>
              (selectedAssistant =
                availableAssistants.find((assistant) => assistant.id === id) ?? selectedAssistant)}
          >
            <Select.Trigger id={`${uid}-assistant`} class="w-full">
              {selectedHandle ?? m.ui_select_placeholder()}
            </Select.Trigger>
            <Select.Content>
              {#each availableAssistants as assistant (assistant.id)}
                <Select.Item value={assistant.id} label={assistant.handle}>
                  {assistant.handle}
                </Select.Item>
              {:else}
                <Select.Item
                  value=""
                  disabled
                  label={m.ui_no_available_items({ resourceName: m.resource_assistants() })}
                >
                  {m.ui_no_available_items({ resourceName: m.resource_assistants() })}
                </Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        </Field.Field>
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
      </div>
    </div>
    <Dialog.Footer class={dialogLayout.footer}>
      <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
      <Button
        disabled={!selectedAssistant}
        onclick={() => {
          if (selectedAssistant) {
            if (!user_description && selectedAssistant.default_description === null) {
              toast.warning(m.description_required_to_add_assistant());
              return;
            }
            addAssistantToGroup({ ...selectedAssistant, user_description });
            user_description = "";
            selectedAssistant = undefined;
            isOpen = false;
          }
        }}>{m.add_to_group()}</Button
      >
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
