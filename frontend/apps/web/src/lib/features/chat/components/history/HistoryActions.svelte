<script lang="ts">
  import { IconTrash } from "@eneo/icons/trash";
  import { IconEdit } from "@eneo/icons/edit";
  import { Button } from "$lib/components/ui/button/index.js";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import NameDialog from "$lib/components/NameDialog.svelte";
  import { getChatService } from "../../ChatService.svelte";
  import type { ConversationSparse } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";

  export let conversation: ConversationSparse;
  export let onConversationDeleted: ((conversation: ConversationSparse) => void) | undefined =
    undefined;

  const chat = getChatService();

  const untitled = m.chat_history_untitled();

  async function deleteConversation() {
    await chat.deleteConversation(conversation);
    onConversationDeleted?.(conversation);
  }
</script>

<div class="flex items-center justify-end gap-2">
  <!-- Rename -->
  <NameDialog
    title={m.chat_history_rename()}
    description={m.chat_history_rename_description()}
    label={m.chat_history_name_label()}
    initial={conversation?.name ?? ""}
    placeholder={conversation?.name ?? untitled}
    submitLabel={m.save()}
    pendingLabel={m.saving()}
    onSubmit={(name) => chat.renameConversation(conversation, name)}
  >
    {#snippet trigger({ props })}
      <Button {...props} variant="ghost" size="icon" aria-label={m.chat_history_rename()}>
        <IconEdit />
      </Button>
    {/snippet}
  </NameDialog>

  <!-- Delete -->
  <ConfirmDialog
    title={m.delete_conversation()}
    confirmLabel={m.delete()}
    onConfirm={deleteConversation}
  >
    {#snippet trigger({ props })}
      <Button {...props} variant="destructive" size="icon" aria-label={m.delete_conversation()}>
        <IconTrash />
      </Button>
    {/snippet}
    {#snippet description()}
      {m.do_you_really_want_to_delete()}
      <span class="italic">{(conversation?.name ?? untitled).slice(0, 200)}</span>?
    {/snippet}
  </ConfirmDialog>
</div>
