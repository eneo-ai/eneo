<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { m } from "$lib/paraglide/messages";

  type PendingConfirm = { messages: string[]; submit: () => Promise<void> };
  type Props = {
    pendingConfirm: PendingConfirm | null;
    saving: boolean;
  };

  let { pendingConfirm = $bindable(), saving }: Props = $props();
</script>

<Dialog.Root
  open={pendingConfirm !== null}
  onOpenChange={(o) => {
    if (!o) pendingConfirm = null;
  }}
>
  <Dialog.Content>
    <Dialog.Header>
      <Dialog.Title>{m.governance_confirm_title()}</Dialog.Title>
      <Dialog.Description>
        {m.governance_confirm_desc()}
      </Dialog.Description>
    </Dialog.Header>
    <ul class="list-disc space-y-1 pl-6 text-sm">
      {#each pendingConfirm?.messages ?? [] as msg (msg)}
        <li>{msg}</li>
      {/each}
    </ul>
    <Dialog.Footer>
      <Button variant="outline" onclick={() => (pendingConfirm = null)} disabled={saving}>
        {m.cancel()}
      </Button>
      <Button onclick={() => pendingConfirm?.submit()} disabled={saving} aria-busy={saving}>
        {saving ? m.governance_saving() : m.governance_confirm_and_save()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
