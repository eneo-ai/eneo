<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { invalidate } from "$app/navigation";
  import { getEneo } from "$lib/core/Eneo";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import { isCapabilityPurpose } from "$lib/features/mcp/capabilities";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { m } from "$lib/paraglide/messages";

  type Props = {
    mcpServer: {
      mcp_server_id: string;
      name: string;
      is_org_enabled: boolean;
      is_enabled?: boolean;
      purpose?: string | null;
    };
    /** Called when a toggle starts, so a stale error from an earlier attempt clears. */
    onAttempt?: () => void;
    /** Receives a message when the switch fails; activation can be refused. */
    onError?: (message: string) => void;
  };

  const { mcpServer, onAttempt, onError }: Props = $props();

  const eneo = getEneo();

  // A capability provider's switch is the atomic activate/deactivate step
  // (one active provider per capability); general servers toggle per tenant.
  const isProvider = $derived(isCapabilityPurpose(mcpServer.purpose));
  const isOn = $derived(isProvider ? !!mcpServer.is_enabled : mcpServer.is_org_enabled);

  async function toggleEnabled() {
    onAttempt?.();
    try {
      if (isProvider) {
        if (isOn) {
          await eneo.mcpServers.deactivate({ id: mcpServer.mcp_server_id });
        } else {
          await eneo.mcpServers.activate({ id: mcpServer.mcp_server_id });
        }
      } else if (isOn) {
        await eneo.mcpServers.disable({ mcp_server_id: mcpServer.mcp_server_id });
      } else {
        await eneo.mcpServers.enable({ mcp_server_id: mcpServer.mcp_server_id, env_vars: {} });
      }
      await Promise.all([
        invalidate("admin:layout"),
        invalidate("spaces:data"),
        invalidate("admin:tools")
      ]);
    } catch (e) {
      console.error(`Error toggling MCP server ${mcpServer.name}:`, e);
      // Provider switches have a translated message; the backend detail
      // (an English reason such as "no enabled tools") follows it.
      const detail = getErrorMessage(e);
      const message = isProvider
        ? [isOn ? m.capability_deactivation_failed() : m.capability_activation_failed(), detail]
            .filter(Boolean)
            .join(" ")
        : detail;
      if (message) onError?.(message);
    }
  }

  const tooltip = $derived(
    isProvider
      ? isOn
        ? m.deactivate()
        : m.capability_activate_hint()
      : isOn
        ? m.click_to_disable()
        : m.click_to_enable()
  );
</script>

<div class="flex items-center">
  <Tooltip.Root>
    <Tooltip.Trigger tabindex={-1}>
      {#snippet child({ props })}
        <div {...props}>
          <Switch
            checked={isOn}
            onCheckedChange={() => toggleEnabled()}
            aria-label={mcpServer.name}
          />
        </div>
      {/snippet}
    </Tooltip.Trigger>
    <Tooltip.Content>{tooltip}</Tooltip.Content>
  </Tooltip.Root>
</div>
