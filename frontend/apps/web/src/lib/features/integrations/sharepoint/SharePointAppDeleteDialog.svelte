<script lang="ts">
  import { onMount } from "svelte";
  import type { Writable } from "svelte/store";
  import { AlertTriangle, LoaderCircle } from "lucide-svelte";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { getEneo } from "$lib/core/Eneo";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";

  let {
    openController,
    onDeleted
  }: {
    openController: Writable<boolean>;
    onDeleted?: () => void;
  } = $props();

  const eneo = getEneo();

  let dialogOpen = $state(false);
  onMount(() => openController.subscribe((value) => (dialogOpen = value)));
  $effect(() => {
    openController.set(dialogOpen);
  });

  let isDeleting = $state(false);
  let confirmationText = $state("");
  const confirmationWord = m.sharepoint_delete_confirmation_word();

  let isConfirmed = $derived(
    confirmationText.trim().toUpperCase() === confirmationWord.toUpperCase()
  );

  async function handleDelete() {
    if (!isConfirmed || isDeleting) return;
    isDeleting = true;

    try {
      await eneo.client.fetch("/api/v1/admin/sharepoint/app", { method: "delete" });
      toast.success(m.sharepoint_app_deleted());
      dialogOpen = false;
      onDeleted?.();
    } catch (error) {
      toastError(error, m.failed_to_delete_sharepoint_app());
    } finally {
      isDeleting = false;
    }
  }

  $effect(() => {
    if (!dialogOpen) confirmationText = "";
  });
</script>

<AlertDialog.Root bind:open={dialogOpen}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.delete_sharepoint_app()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.delete_sharepoint_app_warning()}
      </AlertDialog.Description>
    </AlertDialog.Header>

    <div class="border-destructive/40 bg-destructive/10 rounded-lg border px-4 py-3">
      <div class="flex items-start gap-3">
        <AlertTriangle class="text-destructive mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <div class="flex flex-col gap-2 text-sm">
          <p class="font-semibold">{m.warning_permanent_deletion()}</p>
          <ul class="text-muted-foreground list-inside list-disc space-y-1">
            <li>{m.sharepoint_delete_warning_knowledge()}</li>
            <li>{m.sharepoint_delete_warning_assistants()}</li>
            <li>{m.sharepoint_delete_warning_webhooks()}</li>
            <li>{m.sharepoint_delete_warning_tokens()}</li>
          </ul>
          <p class="text-destructive font-medium">{m.this_cannot_be_undone()}</p>
        </div>
      </div>
    </div>

    <Field.Field>
      <Field.Label for="sharepoint-confirm-delete">
        {m.type_to_confirm({ word: confirmationWord })}
      </Field.Label>
      <Input
        id="sharepoint-confirm-delete"
        bind:value={confirmationText}
        placeholder={confirmationWord}
        autocomplete="off"
        autocorrect="off"
        spellcheck={false}
      />
    </Field.Field>

    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={isDeleting}>{m.cancel()}</AlertDialog.Cancel>
      <Button variant="destructive" onclick={handleDelete} disabled={!isConfirmed || isDeleting}>
        {#if isDeleting}
          <LoaderCircle class="animate-spin" aria-hidden="true" />
        {/if}
        {isDeleting ? m.deleting() : m.permanent_delete()}
      </Button>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
