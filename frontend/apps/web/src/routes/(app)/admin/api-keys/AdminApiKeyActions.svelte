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

  let showRevokeDialog: Dialog.OpenState;
  let showSuspendDialog: Dialog.OpenState;
  let errorMessage: string | null = null;
  let reasonText = "";

  const isActive = $derived(apiKey.state === "active");
  const isSuspended = $derived(apiKey.state === "suspended");
  const canRotate = $derived(apiKey.state === "active");

  async function rotateKey() {
    errorMessage = null;
    try {
      const response = await intric.apiKeys.admin.rotate({ id: apiKey.id });
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
      await intric.apiKeys.admin.revoke({
        id: apiKey.id,
        request: {
          reason_code: "admin_action",
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
      await intric.apiKeys.admin.suspend({
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
      await intric.apiKeys.admin.reactivate({ id: apiKey.id });
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
        {m.api_keys_admin_action_rotate()}
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
        {m.api_keys_admin_action_suspend()}
      </Button>
    {/if}

    {#if isSuspended}
      <Button is={item} padding="icon-leading" on:click={reactivateKey}>
        <RefreshCw size={16} />
        {m.api_keys_admin_action_reactivate()}
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
      {m.api_keys_admin_action_revoke()}
    </Button>
  </Dropdown.Menu>
</Dropdown.Root>

{#if errorMessage}
  <div class="text-xs text-red-600">{errorMessage}</div>
{/if}

<Dialog.Root alert bind:isOpen={showSuspendDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.api_keys_admin_suspend_title()}</Dialog.Title>
    <Dialog.Description>
      {m.api_keys_admin_suspend_description()}
    </Dialog.Description>
    <Input.Text bind:value={reasonText} label={m.api_keys_admin_reason_optional()} />
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={suspendKey}>{m.api_keys_admin_action_suspend()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root alert bind:isOpen={showRevokeDialog}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.api_keys_admin_revoke_title()}</Dialog.Title>
    <Dialog.Description>
      {m.api_keys_admin_revoke_description()}
    </Dialog.Description>
    <Input.Text bind:value={reasonText} label={m.api_keys_admin_reason_optional()} />
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={revokeKey}>{m.api_keys_admin_action_revoke()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
