<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, Dialog } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { AlertTriangle } from "lucide-svelte";
  import type { Writable } from "svelte/store";

  type Props = {
    openController: Writable<boolean>;
    mcpServer: any;
    onDelete: (id: string) => Promise<void>;
  };

  const { openController, mcpServer, onDelete }: Props = $props();

  let isLoading = $state(false);
  let errorMessage = $state("");

  async function handleDelete() {
    errorMessage = "";
    isLoading = true;

    try {
      await onDelete(mcpServer.mcp_server_id);
      $openController = false;
    } catch (error: any) {
      console.error("Error deleting MCP server:", error);
      errorMessage = error?.message || error?.body?.message || "Failed to delete MCP server";
    } finally {
      isLoading = false;
    }
  }
</script>

<Dialog.Root {openController}>
  <Dialog.Content>
    <Dialog.Title>{m.delete_mcp_server()}</Dialog.Title>
    <Dialog.Description>
      {m.delete_mcp_server_confirmation()}
    </Dialog.Description>

    <Dialog.Section>
      <div class="flex flex-col gap-4">
        <div class="rounded-lg border border-warning-default bg-warning-default/15 px-4 py-3">
          <div class="flex items-start gap-3">
            <AlertTriangle class="text-warning-default shrink-0" size={20} />
            <div class="flex flex-col gap-1">
              <div class="font-semibold text-default">{mcpServer.name}</div>
              <div class="text-sm text-dimmer">{m.permanent_action()}</div>
            </div>
          </div>
        </div>

        {#if errorMessage}
          <div class="rounded-lg bg-negative-default/10 px-3 py-2 text-sm text-negative-default">
            {errorMessage}
          </div>
        {/if}
      </div>
    </Dialog.Section>

    <Dialog.Controls let:close>
      <Button is={close} disabled={isLoading}>{m.cancel()}</Button>
      <Button variant="destructive" onclick={handleDelete} disabled={isLoading}>
        {isLoading ? m.deleting() : m.delete()}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
