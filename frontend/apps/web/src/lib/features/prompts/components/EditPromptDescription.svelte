<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getAppContext } from "$lib/core/AppContext";
  import { Button, Dialog, Input, Tooltip } from "@intric/ui";
  import { getPromptManager } from "../PromptManager";
  import type { Prompt } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";

  export let prompt: Prompt;
  let description = prompt.description ?? "";

  const { user } = getAppContext();
  const { updatePromptDescription } = getPromptManager();

  $: isPromptCreatedByUser = user.id === prompt.user.id;
</script>

<Dialog.Root>
  <Dialog.Trigger asFragment let:trigger>
    <Tooltip
      text={!isPromptCreatedByUser
        ? m.only_author_can_change_description()
        : undefined}
    >
      <Button variant="outlined" disabled={!isPromptCreatedByUser} is={trigger}
        >{prompt.description ? m.edit_description() : m.add_description()}</Button
      >
    </Tooltip>
  </Dialog.Trigger>

  <Dialog.Content width="medium" form>
    <Dialog.Title>{m.edit_prompt_description()}</Dialog.Title>

    <Dialog.Section>
      <Input.TextArea
        bind:value={description}
        class="border-default hover:bg-hover-dimmer border-b px-4 py-4"
        rows={3}
      >
        {m.description()}</Input.TextArea
      >
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
