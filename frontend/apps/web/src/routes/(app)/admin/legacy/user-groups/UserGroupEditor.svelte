<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { makeEditable } from "$lib/core/editable";
  import { getEneo } from "$lib/core/Eneo";
  import type { UserGroup } from "@eneo/eneo-js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  const nameId = useId();

  const emptyUserGroup: UserGroup = {
    id: "",
    name: ""
  };

  const eneo = getEneo();

  export let mode: "update" | "create" = "create";
  export let userGroup: UserGroup = emptyUserGroup;

  let showDialog = false;
  let isProcessing = false;

  const editableUserGroup = makeEditable(userGroup ?? emptyUserGroup);

  // Instead of deleting and re-creating this component, sveltekit will update the userGroup variable
  // We update this component's view based on the userGroup's value
  async function watchChanges(userGroup: UserGroup) {
    if (userGroup !== editableUserGroup.getOriginal()) {
      editableUserGroup.updateWithValue(userGroup);
    }
  }

  $: watchChanges(userGroup);

  async function edit() {
    isProcessing = true;
    try {
      const updated = await eneo.userGroups.update({
        userGroup: { id: userGroup.id },
        update: editableUserGroup.getEdits()
      });
      editableUserGroup.updateWithValue(updated);
      invalidate("admin:user-groups:load");
      showDialog = false;
    } catch (error) {
      toastError(error);
      console.error(error);
    }
    isProcessing = false;
  }

  async function create() {
    isProcessing = true;
    try {
      await eneo.userGroups.create(editableUserGroup);
      invalidate("admin:user-groups:load");
      showDialog = false;
      editableUserGroup.updateWithValue(emptyUserGroup);
    } catch (error) {
      toastError(error);
      console.error(error);
    }
    isProcessing = false;
  }
</script>

<Dialog.Root bind:open={showDialog}>
  {#if mode === "create"}
    <Dialog.Trigger>
      {#snippet child({ props })}
        <Button {...props}>{m.create_user_group()}</Button>
      {/snippet}
    </Dialog.Trigger>
  {:else}
    <Dialog.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant="outline">{m.rename()}</Button>
      {/snippet}
    </Dialog.Trigger>
  {/if}

  <Dialog.Content class={dialogLayout.content("medium")} closeLabel={m.close()}>
    <form class="contents" on:submit|preventDefault={() => (mode === "create" ? create() : edit())}>
      <Dialog.Header class={dialogLayout.header}>
        {#if mode === "create"}
          <Dialog.Title>{m.create_new_user_group()}</Dialog.Title>
        {:else}
          <Dialog.Title>{m.rename_user_group()}</Dialog.Title>
        {/if}
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class={dialogLayout.section}>
          <div class="hover:bg-hover-dimmer">
            <Field.Field class="border-default px-4 py-4 {mode === 'create' ? 'border-b' : ''}">
              <Field.Label for={nameId}>
                {m.group_name()}
                <span class="text-muted font-normal" aria-hidden="true">({m.required()})</span>
              </Field.Label>
              <Input
                id={nameId}
                bind:value={editableUserGroup.name}
                required
                aria-describedby={`${nameId}-description`}
              />
              <Field.Description id={`${nameId}-description`}>
                {m.descriptive_name_for_group()}
              </Field.Description>
            </Field.Field>
          </div>
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>
        {#if mode === "create"}
          <Button type="submit" disabled={isProcessing}
            >{isProcessing ? m.creating() : m.create_user_group()}</Button
          >
        {:else}
          <Button type="submit" disabled={isProcessing}
            >{isProcessing ? m.saving() : m.save_changes()}</Button
          >
        {/if}
      </Dialog.Footer>
    </form>
  </Dialog.Content>
</Dialog.Root>
