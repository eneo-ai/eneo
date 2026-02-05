<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@intric/intric-js";
  import { Button, Dialog, Dropdown, Input } from "@intric/ui";
  import { Ban, MoreVertical, RefreshCw, RotateCcw } from "lucide-svelte";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";

  const intric = getIntric();

  let { apiKey, onChanged, onSecret } = $props<{
    apiKey: ApiKeyV2;
    onChanged: () => void;
    onSecret: (response: ApiKeyCreatedResponse) => void;
  }>();

  let showRevokeDialog = $state<Dialog.OpenState>(undefined);
  let showSuspendDialog = $state<Dialog.OpenState>(undefined);
  let errorMessage = $state<string | null>(null);
  let reasonText = $state("");

  const isActive = $derived(apiKey.state === "active");
  const isSuspended = $derived(apiKey.state === "suspended");
  const canRotate = $derived(apiKey.state === "active");

  async function rotateKey() {
    errorMessage = null;
    try {
      const response = await intric.apiKeys.rotate({ id: apiKey.id });
      onSecret(response);
      onChanged();
    } catch (error) {
      console.error(error);
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    }
  }

  async function revokeKey() {
    errorMessage = null;
    try {
      await intric.apiKeys.revoke({
        id: apiKey.id,
        request: {
          reason_code: "user_request",
          reason_text: reasonText || undefined
        }
      });
      onChanged();
      showRevokeDialog = false;
      reasonText = "";
    } catch (error) {
      console.error(error);
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    }
  }

  async function suspendKey() {
    errorMessage = null;
    try {
      await intric.apiKeys.suspend({
        id: apiKey.id,
        request: {
          reason_code: "security_concern",
          reason_text: reasonText || undefined
        }
      });
      onChanged();
      showSuspendDialog = false;
      reasonText = "";
    } catch (error) {
      console.error(error);
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    }
  }

  async function reactivateKey() {
    errorMessage = null;
    try {
      await intric.apiKeys.reactivate({ id: apiKey.id });
      onChanged();
    } catch (error) {
      console.error(error);
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    }
  }
</script>

<Dropdown.Root>
  <Dropdown.Trigger asFragment let:trigger>
    <Button is={trigger} padding="icon" aria-label={m.actions()}>
      <MoreVertical size={16} />
    </Button>
  </Dropdown.Trigger>

  <Dropdown.Menu let:item>
    {#if canRotate}
      <Button is={item} padding="icon-leading" on:click={rotateKey}>
        <RotateCcw size={16} />
        Rotate
      </Button>
    {/if}

    {#if isActive}
      <Button
        is={item}
        padding="icon-leading"
        on:click={() => {
          showSuspendDialog = true;
        }}
      >
        <Ban size={16} />
        Suspend
      </Button>
    {/if}

    {#if isSuspended}
      <Button is={item} padding="icon-leading" on:click={reactivateKey}>
        <RefreshCw size={16} />
        Reactivate
      </Button>
    {/if}

    <Button
      is={item}
      variant="destructive"
      padding="icon-leading"
      on:click={() => {
        showRevokeDialog = true;
      }}
    >
      <Ban size={16} />
      Revoke
    </Button>
  </Dropdown.Menu>
</Dropdown.Root>

{#if errorMessage}
  <div class="text-xs text-negative">{errorMessage}</div>
{/if}

<Dialog.Root alert bind:isOpen={showSuspendDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>Suspend API key</Dialog.Title>
    <Dialog.Description>
      This key will be temporarily disabled and can be reactivated later.
    </Dialog.Description>
    <Input.Text bind:value={reasonText} label="Reason (optional)" />
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={suspendKey}>Suspend</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root alert bind:isOpen={showRevokeDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>Revoke API key</Dialog.Title>
    <Dialog.Description>
      This key will be permanently revoked. Existing integrations will stop working.
    </Dialog.Description>
    <Input.Text bind:value={reasonText} label="Reason (optional)" />
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={revokeKey}>Revoke</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
