<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { dialogLayout } from "$lib/components/dialogLayout.js";
  import { m } from "$lib/paraglide/messages";
  import { AlertTriangle } from "@lucide/svelte";
  import type { Writable } from "svelte/store";
  import type { components } from "@eneo/eneo-js";

  type MCPServerSettings = components["schemas"]["MCPServerSettingsPublic"];

  type Props = {
    openController: Writable<boolean>;
    mcpServer: MCPServerSettings;
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
    } catch (error: unknown) {
      console.error("Error deleting MCP server:", error);
      const err = error as { message?: string; body?: { message?: string } };
      errorMessage = err?.message || err?.body?.message || "Failed to delete MCP server";
    } finally {
      isLoading = false;
    }
  }
</script>

<Dialog.Root bind:open={$openController}>
  <Dialog.Content class={dialogLayout.content()} closeLabel={m.close()}>
    <Dialog.Header class={dialogLayout.header}>
      <Dialog.Title>{m.delete_mcp_server()}</Dialog.Title>
      <Dialog.Description>
        {m.delete_mcp_server_confirmation()}
      </Dialog.Description>
    </Dialog.Header>

    <div class={dialogLayout.body}>
      <div class={dialogLayout.section}>
        <div class="flex flex-col gap-4">
          <div class="border-warning-default bg-warning-default/15 rounded-lg border px-4 py-3">
            <div class="flex items-start gap-3">
              <AlertTriangle class="text-warning-default shrink-0" size={20} />
              <div class="flex flex-col gap-1">
                <div class="text-default font-semibold">{mcpServer.name}</div>
                <div class="text-dimmer text-sm">{m.permanent_action()}</div>
              </div>
            </div>
          </div>

          {#if errorMessage}
            <div class="bg-negative-default/10 text-negative-default rounded-lg px-3 py-2 text-sm">
              {errorMessage}
            </div>
          {/if}
        </div>
      </div>
    </div>

    <Dialog.Footer class={dialogLayout.footer}>
      <Dialog.Close class={buttonVariants({ variant: "outline" })} disabled={isLoading}>
        {m.cancel()}
      </Dialog.Close>
      <Button variant="destructive" onclick={handleDelete} disabled={isLoading}>
        {isLoading ? m.deleting() : m.delete()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
