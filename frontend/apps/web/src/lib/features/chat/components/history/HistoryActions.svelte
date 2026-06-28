<script lang="ts">
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEdit } from "@eneo/icons/edit";
  import { Button, Dialog, Input } from "@eneo/ui";
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

  let renameOpen: Dialog.OpenState;

  async function submitRename() {
    const trimmed = (newName ?? "").trim();
    if (!trimmed) return;

    try {
      await chat.renameConversation(conversation, trimmed);
      $renameOpen = false;
    } catch (e) {
      toastError(e);
    }
  }
</script>

<div class="flex items-center justify-end gap-2">
  <!-- Rename -->
  <Dialog.Root bind:isOpen={renameOpen}>
    <Dialog.Trigger asFragment let:trigger>
      <Button is={trigger} label={m.chat_history_rename()} padding="icon">
        <IconEdit />
      </Button>
    </Dialog.Trigger>

    <Dialog.Content width="small">
      <Dialog.Title>{m.chat_history_rename()}</Dialog.Title>
      <Dialog.Description>{m.chat_history_rename_description()}</Dialog.Description>

      <Dialog.Section class="p-6">
        <div class="flex flex-col gap-3">
          <label for="rename-name" class="text-default text-sm font-medium">
            {m.chat_history_name_label()}
          </label>

          <Input.Text
            id="rename-name"
            bind:value={newName}
            placeholder={conversation?.name ?? untitled}
          />
        </div>
      </Dialog.Section>

      <Dialog.Controls let:close>
        <Button is={close}>{m.cancel()}</Button>

        <Button disabled={(newName ?? "").trim().length === 0} on:click={submitRename}>
          {m.save()}
        </Button>
      </Dialog.Controls>
    </Dialog.Content>
  </Dialog.Root>

  <!-- Delete -->
  <Dialog.Root alert>
    <Dialog.Trigger asFragment let:trigger>
      <Button variant="destructive" is={trigger} label={m.delete_conversation()} padding="icon">
        <IconTrash />
      </Button>
    </Dialog.Trigger>

    <Dialog.Content width="small">
      <Dialog.Title>{m.delete_conversation()}</Dialog.Title>
      <Dialog.Description>
        {m.do_you_really_want_to_delete()}
        <span class="italic">{(conversation?.name ?? untitled).slice(0, 200)}</span>?
      </Dialog.Description>

      <Dialog.Controls let:close>
        <Button is={close}>{m.cancel()}</Button>
        <Button
          is={close}
          variant="destructive"
          on:click={async () => {
            await chat.deleteConversation(conversation);
            onConversationDeleted?.(conversation);
          }}
        >
          {m.delete()}
        </Button>
      </Dialog.Controls>
    </Dialog.Content>
  </Dialog.Root>
</div>
