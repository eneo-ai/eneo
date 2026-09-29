<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { getAppContext } from "$lib/core/AppContext";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
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

  let isOpen = false;

  $: isPromptCreatedByUser = user.id === prompt.user.id;

  function saveDescription() {
    updatePromptDescription({
      id: prompt.id,
      description
    });
    isOpen = false;
  }
</script>

<Dialog.Root bind:open={isOpen}>
  {#if isPromptCreatedByUser}
    <Dialog.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant="outline"
          >{prompt.description ? m.edit_description() : m.add_description()}</Button
        >
      {/snippet}
    </Dialog.Trigger>
  {:else}
    <Tooltip.Root>
      <Tooltip.Trigger>
        {#snippet child({ props })}
          <span {...props} class="flex">
            <Button variant="outline" disabled
              >{prompt.description ? m.edit_description() : m.add_description()}</Button
            >
          </span>
        {/snippet}
      </Tooltip.Trigger>
      <Tooltip.Content>{m.only_author_can_change_description()}</Tooltip.Content>
    </Tooltip.Root>
  {/if}

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form class="contents" on:submit|preventDefault={saveDescription}>
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{m.edit_prompt_description()}</Dialog.Title>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          <Field.Field class="border-default hover:bg-hover-dimmer border-b px-4 py-4">
            <Field.Label for={descriptionId}>{m.description()}</Field.Label>
            <Textarea id={descriptionId} bind:value={description} rows={3} />
          </Field.Field>
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
        <Button type="submit">{m.save_changes()}</Button>
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
