<script lang="ts">
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEdit } from "@eneo/icons/edit";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { useId } from "bits-ui";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { getChatService } from "../../ChatService.svelte";
  import type { ConversationSparse } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";
  import { toastError } from "$lib/core/errors";

  export let conversation: ConversationSparse;
  export let onConversationDeleted: ((conversation: ConversationSparse) => void) | undefined =
    undefined;

  const chat = getChatService();

  let newName = "";
  $: newName = conversation?.name ?? "";

  const untitled = m.chat_history_untitled();
  const renameId = useId();

  let renameOpen = false;
  let deleteOpen = false;

  async function submitRename() {
    const trimmed = (newName ?? "").trim();
    if (!trimmed) return;

    try {
      await chat.renameConversation(conversation, trimmed);
      renameOpen = false;
    } catch (e) {
      toastError(e);
    }
  }

  async function deleteConversation() {
    deleteOpen = false;
    await chat.deleteConversation(conversation);
    onConversationDeleted?.(conversation);
  }
</script>

<div class="flex items-center justify-end gap-2">
  <!-- Rename -->
  <Dialog.Root bind:open={renameOpen}>
    <Dialog.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant="ghost" size="icon" aria-label={m.chat_history_rename()}>
          <IconEdit />
        </Button>
      {/snippet}
    </Dialog.Trigger>

    <Dialog.Content class={dialogLayout.content("small")} closeLabel={m.close()}>
      <Dialog.Header class={dialogLayout.header}>
        <Dialog.Title>{m.chat_history_rename()}</Dialog.Title>
        <Dialog.Description>{m.chat_history_rename_description()}</Dialog.Description>
      </Dialog.Header>

      <div class={dialogLayout.body}>
        <div class="{dialogLayout.section} p-6">
          <Field.Field class="gap-3">
            <Field.Label for={renameId} class="text-default text-sm font-medium">
              {m.chat_history_name_label()}
            </Field.Label>

            <Input
              id={renameId}
              bind:value={newName}
              placeholder={conversation?.name ?? untitled}
            />
          </Field.Field>
        </div>
      </div>

      <Dialog.Footer class={dialogLayout.footer}>
        <Dialog.Close class={buttonVariants({ variant: "outline" })}>{m.cancel()}</Dialog.Close>

        <Button disabled={(newName ?? "").trim().length === 0} onclick={submitRename}>
          {m.save()}
        </Button>
      </Dialog.Footer>
    </Dialog.Content>
  </Dialog.Root>

  <!-- Delete -->
  <AlertDialog.Root bind:open={deleteOpen}>
    <AlertDialog.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant="destructive" size="icon" aria-label={m.delete_conversation()}>
          <IconTrash />
        </Button>
      {/snippet}
    </AlertDialog.Trigger>

    <AlertDialog.Content class={dialogLayout.content("small")}>
      <AlertDialog.Header class={dialogLayout.header}>
        <AlertDialog.Title>{m.delete_conversation()}</AlertDialog.Title>
        <AlertDialog.Description>
          {m.do_you_really_want_to_delete()}
          <span class="italic">{(conversation?.name ?? untitled).slice(0, 200)}</span>?
        </AlertDialog.Description>
      </AlertDialog.Header>

      <AlertDialog.Footer class={dialogLayout.footer}>
        <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
        <Button variant="destructive" onclick={deleteConversation}>
          {m.delete()}
        </Button>
      </AlertDialog.Footer>
    </AlertDialog.Content>
  </AlertDialog.Root>
</div>
