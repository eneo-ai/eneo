<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { IconCog } from "@eneo/icons/cog";
  import type { GroupChat } from "@eneo/eneo-js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";

  type AssistantTool = GroupChat["tools"]["assistants"][number];
  type Props = {
    updateAssistant: (assistant: AssistantTool) => void;
    assistant: AssistantTool;
  };

  const { assistant, updateAssistant }: Props = $props();
  const uid = $props.id();

  let descriptionProxy = $derived.by(() => {
    let value = $state(assistant.user_description ?? "");
    return { value };
  });

  let isOpen = $state(false);
</script>

<Dialog.Root bind:open={isOpen}>
  <Dialog.Trigger>
    {#snippet child({ props })}
      <Button {...props} variant="outline" size="icon" aria-label={m.edit_assistant_description()}
        ><IconCog></IconCog></Button
      >
    {/snippet}
  </Dialog.Trigger>

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.edit_assistant_description()}</Dialog.Title>
    </Dialog.Header>
    <div class={dialogLayout.body}>
      <div class={dialogLayout.section}>
        <Field.Field class="border-default hover:bg-hover-dimmer border-b px-4 py-4">
          <Field.Label for={`${uid}-handle`}>{m.assistant()}</Field.Label>
          <Input
            id={`${uid}-handle`}
            value={assistant.handle}
            disabled
            class="text-secondary pointer-events-none"
          />
        </Field.Field>
        <Field.Field class="border-default hover:bg-hover-dimmer px-4 py-4">
          <Field.Label for={`${uid}-description`}>{m.description()}</Field.Label>
          <Textarea
            id={`${uid}-description`}
            bind:value={descriptionProxy.value}
            rows={4}
            placeholder={assistant?.default_description}
            aria-describedby={`${uid}-description-description`}
          />
          <Field.Description id={`${uid}-description-description`}>
            {m.will_help_determine_assistant()}
          </Field.Description>
        </Field.Field>
      </div>
    </div>
    <Dialog.Footer class={dialogLayout.footer}>
      <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
      <Button
        onclick={() => {
          const user_description =
            descriptionProxy.value.trim() === "" ? null : descriptionProxy.value;
          if (!user_description && !assistant.default_description) {
            toast.warning(m.description_required_for_assistant());
            return;
          }
          updateAssistant({ ...assistant, user_description });
          isOpen = false;
        }}>{m.accept_changes()}</Button
      >
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
