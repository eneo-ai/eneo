<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Licensed under the MIT License.

  The action a tool step offers when its OAuth server has no authorization
  for the user: a button that runs the connect popup for a per-user server,
  or a note that an administrator has to connect a shared one.
-->
<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { toast } from "$lib/components/toast";
  import { toastError } from "$lib/core/errors";
  import { m } from "$lib/paraglide/messages";
  import { getMcpOAuthConnect } from "$lib/features/mcp/McpOAuthConnectService.svelte";
  import type { AuthorizationRemedy } from "$lib/features/mcp/oauthRemedy";
  import { Plug } from "@lucide/svelte";

  let { remedy, live = false }: { remedy: AuthorizationRemedy; live?: boolean } = $props();

  const connect = getMcpOAuthConnect();
  let connected = $state(false);

  async function run() {
    if (!connect) return;
    const result = await connect.connect(remedy.mcp_server_id);
    if (result.success) {
      connected = true;
      // A live turn resumes the call by itself; a finished one needs a resend.
      toast.success(live ? m.mcp_oauth_connected_continuing() : m.mcp_oauth_connected_resend());
    } else if (result.error.message !== "popup_closed") {
      toastError(result.error);
    }
  }
</script>

{#if remedy.auth_scope === "shared"}
  <span class="text-muted text-xs">{m.mcp_oauth_needs_admin({ server: remedy.server_name })}</span>
{:else if connected}
  <span class="text-positive-default text-xs"
    >{live ? m.mcp_oauth_connected_continuing() : m.mcp_oauth_connected_resend()}</span
  >
{:else if connect}
  <Button
    variant="outline"
    size="sm"
    class="h-7 gap-1.5 text-xs"
    disabled={connect.isConnecting(remedy.mcp_server_id)}
    onclick={run}
  >
    <Plug class="size-3.5" aria-hidden="true" />
    {m.mcp_oauth_connect_server({ server: remedy.server_name })}
  </Button>
{/if}
