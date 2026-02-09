<script lang="ts">
  import { IconTrash } from "@intric/icons/trash";
  import { IconEdit } from "@intric/icons/edit";
  import { Button, Dialog } from "@intric/ui";
  import { getChatService } from "../../ChatService.svelte";
  import type { ConversationSparse } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";

  export let conversation: ConversationSparse;
  export let onConversationDeleted: ((conversation: ConversationSparse) => void) | undefined =
    undefined;

  const chat = getChatService();

  let newName = "";
  $: newName = conversation?.name ?? "";

  const untitled = "Namnlös";
</script>

<div class="flex items-center justify-end gap-2">
  <!-- Rename -->
  <Dialog.Root>
    <Dialog.Trigger asFragment let:trigger>
      <span on:click|stopPropagation>
        <Button is={trigger} label="Byt namn" padding="icon">
          <IconEdit />
        </Button>
      </span>
    </Dialog.Trigger>

    <Dialog.Content width="small">
      <Dialog.Title>Byt namn</Dialog.Title>
      <Dialog.Description>Skriv ett nytt namn för konversationen.</Dialog.Description>

      <div class="mt-4">
        <label for="rename-name" class="mb-2 block text-sm font-medium">Namn</label>

        <input
          id="rename-name"
          class="w-full rounded-md border border-white/10 bg-white/5 px-3 py-2 text-sm outline-none focus:border-white/20"
          bind:value={newName}
          placeholder={conversation?.name ?? untitled}
        />
      </div>

      <Dialog.Controls let:close>
        <Button is={close}>{m.cancel()}</Button>

        <Button
          is={close}
          disabled={(newName ?? "").trim().length === 0}
          on:click={async () => {
            const trimmed = (newName ?? "").trim();
            if (!trimmed) return;

            await chat.renameConversation(conversation, trimmed);
          }}
        >
          Spara
        </Button>
      </Dialog.Controls>
    </Dialog.Content>
  </Dialog.Root>

  <!-- Delete -->
  <Dialog.Root alert>
    <Dialog.Trigger asFragment let:trigger>
      <span on:click|stopPropagation>
        <Button variant="destructive" is={trigger} label={m.delete_conversation()} padding="icon">
          <IconTrash />
        </Button>
      </span>
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
