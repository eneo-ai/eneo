<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getAppContext } from "$lib/core/AppContext";
  import { Button, Dialog } from "@eneo/ui";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { getPromptManager } from "../PromptManager";
  import type { Prompt } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";

  export let prompt: Prompt;
  let description = prompt.description ?? "";
  const descriptionId = useId();

  const { user } = getAppContext();
  const { updatePromptDescription } = getPromptManager();

  $: isPromptCreatedByUser = user.id === prompt.user.id;
</script>

<Dialog.Root>
  <Dialog.Trigger asFragment let:trigger>
    {#if isPromptCreatedByUser}
      <Button variant="outlined" is={trigger}
        >{prompt.description ? m.edit_description() : m.add_description()}</Button
      >
    {:else}
      <Tooltip.Root>
        <Tooltip.Trigger>
          {#snippet child({ props })}
            <span {...props} class="flex">
              <Button variant="outlined" disabled is={trigger}
                >{prompt.description ? m.edit_description() : m.add_description()}</Button
              >
            </span>
          {/snippet}
        </Tooltip.Trigger>
        <Tooltip.Content>{m.only_author_can_change_description()}</Tooltip.Content>
      </Tooltip.Root>
    {/if}
  </Dialog.Trigger>

  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.edit_prompt_description()}</Dialog.Title>

    <Dialog.Section>
      <Field.Field class="border-default hover:bg-hover-dimmer border-b px-4 py-4">
        <Field.Label for={descriptionId}>{m.description()}</Field.Label>
        <Textarea id={descriptionId} bind:value={description} rows={3} />
      </Field.Field>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button
        variant="primary"
        is={close}
        on:click={() => {
          updatePromptDescription({
            id: prompt.id,
            description
          });
        }}>{m.save_changes()}</Button
      >
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
