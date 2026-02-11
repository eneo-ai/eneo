<script lang="ts">
  import { Button, Dialog, Input } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { AlertTriangle } from "lucide-svelte";
  import type { Writable } from "svelte/store";
  import { getIntric } from "$lib/core/Intric";

  let { openController }: { openController: Writable<boolean> } = $props();

  const intric = getIntric();

  let isLoading = $state(false);
  let errorMessage = $state("");
  let confirmationText = $state("");
  const CONFIRMATION_WORD = "DELETE";

  let isConfirmed = $derived(confirmationText.trim().toUpperCase() === CONFIRMATION_WORD);

  async function handleDelete() {
    console.log("handleDelete called, isConfirmed:", isConfirmed);
    if (!isConfirmed) {
      console.log("Not confirmed, returning");
      return;
    }

    console.log("Starting deletion...");
    isLoading = true;
    errorMessage = "";

    try {
      console.log("Calling API to delete SharePoint app...");
      await intric.client.fetch("/api/v1/admin/sharepoint/app", {
        method: "delete",
        params: {}
      });
      console.log("API call successful");
      $openController = false;
      // Reload page to refresh state
      window.location.reload();
    } catch (error: any) {
      console.error("Error deleting SharePoint app:", error);
      errorMessage = error.message || m.failed_to_delete_sharepoint_app();
    } finally {
      isLoading = false;
    }
  }

  // Reset form when dialog closes
  $effect(() => {
    if (!$openController) {
      confirmationText = "";
      errorMessage = "";
    }
  });
</script>

<Dialog.Root openController={openController}>
  <Dialog.Content>
    <Dialog.Title>{m.delete_sharepoint_app()}</Dialog.Title>
    <Dialog.Description>
      {m.delete_sharepoint_app_warning()}
    </Dialog.Description>

    <Dialog.Section class="p-6">
      <!-- Warning box -->
      <div class="rounded-lg border border-negative-default bg-negative-default/15 px-6 py-4 mb-6">
        <div class="flex items-start gap-3">
          <AlertTriangle class="text-negative-default shrink-0" size={20} />
          <div class="flex flex-col gap-2 text-sm">
            <div class="font-semibold text-default">
              {m.warning_permanent_deletion()}
            </div>
            <ul class="list-disc list-inside text-secondary space-y-1">
              <li>{m.sharepoint_delete_warning_knowledge()}</li>
              <li>{m.sharepoint_delete_warning_assistants()}</li>
              <li>{m.sharepoint_delete_warning_webhooks()}</li>
              <li>{m.sharepoint_delete_warning_tokens()}</li>
            </ul>
            <div class="font-medium text-negative-default mt-2">
              {m.this_cannot_be_undone()}
            </div>
          </div>
        </div>
      </div>

      <!-- Confirmation input -->
      <div class="flex flex-col gap-3">
        <label for="confirm-delete" class="text-sm font-medium text-default">
          {m.type_to_confirm({ word: CONFIRMATION_WORD })}
        </label>
        <Input.Text
          id="confirm-delete"
          bind:value={confirmationText}
          placeholder={CONFIRMATION_WORD}
          autocomplete="off"
          autocorrect="off"
          spellcheck={false}
        />
      </div>

      {#if errorMessage}
        <div class="rounded-lg bg-negative-default/10 px-3 py-2 text-sm text-negative-default mt-4">
          {errorMessage}
        </div>
      {/if}
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close} disabled={isLoading}>{m.cancel()}</Button>
      <Button
        variant="destructive"
        onclick={handleDelete}
        disabled={!isConfirmed || isLoading}
      >
        {isLoading ? m.deleting() : m.permanent_delete()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
