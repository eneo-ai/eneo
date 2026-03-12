<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { Input, Tooltip } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    mcpServer: {
      mcp_server_id: string;
      name: string;
      is_org_enabled: boolean;
    };
  };

  const { mcpServer }: Props = $props();

  const intric = getIntric();

  async function toggleEnabled() {
    try {
      if (mcpServer.is_org_enabled) {
        await intric.mcpServers.disable({ mcp_server_id: mcpServer.mcp_server_id });
      } else {
        await intric.mcpServers.enable({ mcp_server_id: mcpServer.mcp_server_id, env_vars: {} });
      }
      await Promise.all([invalidate("admin:layout"), invalidate("spaces:data")]);
    } catch (e) {
      console.error(`Error toggling MCP server ${mcpServer.name}:`, e);
    }
  }

  const tooltip = $derived(mcpServer.is_org_enabled ? m.click_to_disable() : m.click_to_enable());
</script>

<div class="-ml-3 flex items-center gap-4">
  <Tooltip text={tooltip}>
    <Input.Switch sideEffect={toggleEnabled} value={mcpServer.is_org_enabled}></Input.Switch>
  </Tooltip>
</div>
