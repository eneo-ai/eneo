<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import type { components } from "@eneo/eneo-js";
  import { AlertTriangle } from "@lucide/svelte";
  import ConfirmDialog from "$lib/components/ConfirmDialog.svelte";
  import { m } from "$lib/paraglide/messages";

  type MCPServerSettings = components["schemas"]["MCPServerSettingsPublic"];

  type Props = {
    open?: boolean;
    mcpServer: MCPServerSettings;
    onDelete: (id: string) => Promise<void>;
  };

  let { open = $bindable(false), mcpServer, onDelete }: Props = $props();
</script>

<ConfirmDialog
  bind:open
  title={m.delete_mcp_server()}
  description={m.delete_mcp_server_confirmation()}
  confirmLabel={m.delete()}
  pendingLabel={m.deleting()}
  errorContext={m.failed_to_delete_mcp_server()}
  onConfirm={() => onDelete(mcpServer.mcp_server_id)}
>
  <div class="border-warning-default bg-warning-default/15 rounded-lg border px-4 py-3">
    <div class="flex items-start gap-3">
      <AlertTriangle class="text-warning-default shrink-0" size={20} aria-hidden="true" />
      <div class="flex flex-col gap-1">
        <div class="text-default font-semibold">{mcpServer.name}</div>
        <div class="text-muted text-sm">{m.permanent_action()}</div>
      </div>
    </div>
  </div>
</ConfirmDialog>
