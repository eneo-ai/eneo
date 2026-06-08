<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@intric/intric-js";
  import {
    AlertCircle,
    Ban,
    Bell,
    BellOff,
    CalendarClock,
    Eye,
    MoreVertical,
    Pencil,
    RefreshCw,
    RotateCcw,
    Trash2
  } from "lucide-svelte";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "svelte-sonner";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import {
    followApiKeyNotifications,
    unfollowApiKeyNotifications
  } from "$lib/features/api-keys/notificationPreferences";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import ExtendExpirationDialog from "$lib/features/api-keys/ExtendExpirationDialog.svelte";
  import RotateApiKeyDialog from "$lib/features/api-keys/RotateApiKeyDialog.svelte";

  const intric = getIntric();

  let {
    apiKey,
    mode = "user",
    onChanged,
    onSecret,
    onEditRequested,
    onViewRequested,
    isFollowed = false,
    isFollowedViaScope = false,
    onFollowChanged,
    currentUserId = undefined
  } = $props<{
    apiKey: ApiKeyV2;
    mode?: "user" | "admin";
    onChanged: () => void;
    onSecret: (response: ApiKeyCreatedResponse) => void;
    onEditRequested?: () => void;
    onViewRequested?: () => void;
    isFollowed?: boolean;
    isFollowedViaScope?: boolean;
    onFollowChanged?: () => void | Promise<void>;
    currentUserId?: string;
  }>();

  let showRevokeDialog = $state(false);
  let showSuspendDialog = $state(false);
  let showRotateDialog = $state(false);
  let showExtendDialog = $state(false);
  let showPurgeDialog = $state(false);
  let actionPending = $state(false);
  let errorMessage = $state<string | null>(null);
  let reasonText = $state("");
  let followLoading = $state(false);

  const isActive = $derived(apiKey.state === "active");
  const isSuspended = $derived(apiKey.state === "suspended");
  const canRotate = $derived(apiKey.state === "active");
  const canExtendExpiration = $derived(apiKey.state === "active" || apiKey.state === "suspended");
  const canPurge = $derived(apiKey.state === "revoked" || apiKey.state === "expired");
  const isAdmin = $derived(mode === "admin");
  const reasonCode = $derived(isAdmin ? ("admin_action" as const) : ("user_request" as const));
  // In user mode, personal keys can only be managed by their owner; service keys are
  // manageable by any scope-authorized user. Admin mode bypasses ownership (scope
  // authorization is enforced by the backend instead).
  const canManage = $derived(
    isAdmin ||
      !currentUserId ||
      apiKey.ownership === "service" ||
      apiKey.owner_user_id === currentUserId
  );

  async function revokeKey() {
    errorMessage = null;
    actionPending = true;
    try {
      const request = {
        reason_code: reasonCode,
        reason_text: reasonText || undefined
      };
      if (isAdmin) {
        await intric.apiKeys.admin.revoke({ id: apiKey.id, request });
      } else {
        await intric.apiKeys.revoke({ id: apiKey.id, request });
      }
      onChanged();
      showRevokeDialog = false;
      reasonText = "";
      if (!isAdmin) toast.success(m.api_keys_action_revoke());
    } catch (error) {
      console.error(error);
      errorMessage = getErrorMessage(error);
      toast.error(getErrorMessage(error));
    } finally {
      actionPending = false;
    }
  }

  async function suspendKey() {
    errorMessage = null;
    actionPending = true;
    try {
      const request = {
        reason_code: reasonCode,
        reason_text: reasonText || undefined
      };
      if (isAdmin) {
        await intric.apiKeys.admin.suspend({ id: apiKey.id, request });
      } else {
        await intric.apiKeys.suspend({ id: apiKey.id, request });
      }
      onChanged();
      showSuspendDialog = false;
      reasonText = "";
      if (!isAdmin) toast.success(m.api_keys_action_suspend());
    } catch (error) {
      console.error(error);
      errorMessage = getErrorMessage(error);
      toast.error(getErrorMessage(error));
    } finally {
      actionPending = false;
    }
  }

  async function reactivateKey() {
    try {
      if (isAdmin) {
        await intric.apiKeys.admin.reactivate({ id: apiKey.id });
      } else {
        await intric.apiKeys.reactivate({ id: apiKey.id });
      }
      onChanged();
      if (!isAdmin) toast.success(m.api_keys_action_reactivate());
    } catch (error) {
      console.error(error);
      toast.error(getErrorMessage(error));
    }
  }

  async function purgeKey() {
    actionPending = true;
    try {
      if (isAdmin) {
        await intric.apiKeys.admin.purge({ id: apiKey.id });
      } else {
        await intric.apiKeys.purge({ id: apiKey.id });
      }
      onChanged();
      showPurgeDialog = false;
      toast.success(m.api_keys_action_purge());
    } catch (error) {
      console.error(error);
      toast.error(getErrorMessage(error));
    } finally {
      actionPending = false;
    }
  }

  async function toggleFollow() {
    followLoading = true;
    try {
      if (isFollowed) {
        await unfollowApiKeyNotifications(intric, apiKey.id);
      } else {
        await followApiKeyNotifications(intric, apiKey.id);
      }
      await onFollowChanged?.();
    } catch (error) {
      console.error(error);
      toast.error(getErrorMessage(error));
    } finally {
      followLoading = false;
    }
  }
</script>

{#if apiKey.state !== "revoked" || isAdmin || canPurge}
  <DropdownMenu.Root>
    <DropdownMenu.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
          <MoreVertical />
        </Button>
      {/snippet}
    </DropdownMenu.Trigger>

    <DropdownMenu.Content align="end">
      {#if onViewRequested}
        <DropdownMenu.Item onclick={onViewRequested}>
          <Eye />
          {m.api_keys_view_action()}
        </DropdownMenu.Item>
      {/if}

      {#if onEditRequested}
        <DropdownMenu.Item onclick={onEditRequested} disabled={!canManage}>
          <Pencil />
          {m.api_keys_admin_action_edit()}
        </DropdownMenu.Item>
      {/if}

      {#if canRotate}
        <DropdownMenu.Item onclick={() => (showRotateDialog = true)} disabled={!canManage}>
          <RotateCcw />
          {isAdmin ? m.api_keys_admin_action_rotate() : m.api_keys_action_rotate()}
        </DropdownMenu.Item>
      {/if}

      {#if canExtendExpiration}
        <DropdownMenu.Item onclick={() => (showExtendDialog = true)} disabled={!canManage}>
          <CalendarClock />
          {isAdmin ? m.api_keys_admin_action_extend() : m.api_keys_action_extend()}
        </DropdownMenu.Item>
      {/if}

      {#if !isAdmin}
        {#if isFollowedViaScope}
          <DropdownMenu.Item disabled>
            <Bell />
            {m.api_keys_notifications_followed_via_scope()}
          </DropdownMenu.Item>
        {:else if apiKey.state !== "revoked" && apiKey.state !== "expired"}
          <DropdownMenu.Item onclick={toggleFollow} disabled={followLoading}>
            {#if isFollowed}
              <BellOff />
              {m.api_keys_notifications_unfollow_action()}
            {:else}
              <Bell />
              {m.api_keys_notifications_follow_action()}
            {/if}
          </DropdownMenu.Item>
        {/if}
      {/if}

      {#if isActive}
        <DropdownMenu.Item
          onclick={() => {
            showSuspendDialog = true;
          }}
          disabled={!canManage}
        >
          <Ban />
          {isAdmin ? m.api_keys_admin_action_suspend() : m.api_keys_action_suspend()}
        </DropdownMenu.Item>
      {/if}

      {#if isSuspended}
        <DropdownMenu.Item onclick={reactivateKey} disabled={!canManage}>
          <RefreshCw />
          {isAdmin ? m.api_keys_admin_action_reactivate() : m.api_keys_action_reactivate()}
        </DropdownMenu.Item>
      {/if}

      {#if apiKey.state !== "revoked"}
        <DropdownMenu.Separator />

        <DropdownMenu.Item
          variant="destructive"
          onclick={() => {
            showRevokeDialog = true;
          }}
          disabled={!canManage}
        >
          <Ban />
          {isAdmin ? m.api_keys_admin_action_revoke() : m.api_keys_action_revoke()}
        </DropdownMenu.Item>
      {/if}

      {#if canPurge}
        <DropdownMenu.Separator />
        <DropdownMenu.Item
          variant="destructive"
          onclick={() => (showPurgeDialog = true)}
          disabled={!canManage}
        >
          <Trash2 />
          {isAdmin ? m.api_keys_admin_action_purge() : m.api_keys_action_purge()}
        </DropdownMenu.Item>
      {/if}
    </DropdownMenu.Content>
  </DropdownMenu.Root>
{/if}

<!-- Suspend dialog -->
<Dialog.Root bind:open={showSuspendDialog}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>
        {isAdmin ? m.api_keys_admin_suspend_title() : m.api_keys_action_suspend_title()}
      </Dialog.Title>
      <Dialog.Description>
        {isAdmin ? m.api_keys_admin_suspend_description() : m.api_keys_action_suspend_description()}
      </Dialog.Description>
    </Dialog.Header>

    {#if errorMessage}
      <Alert.Root variant="destructive">
        <AlertCircle />
        <Alert.Description>{errorMessage}</Alert.Description>
      </Alert.Root>
    {/if}

    <Field.Field>
      <Field.Label for="suspend-reason">
        {isAdmin ? m.api_keys_admin_reason_optional() : m.api_keys_action_reason_optional()}
      </Field.Label>
      <Input id="suspend-reason" bind:value={reasonText} />
    </Field.Field>

    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>{m.cancel()}</Button>
        {/snippet}
      </Dialog.Close>
      <Button variant="destructive" onclick={suspendKey} disabled={actionPending}>
        {isAdmin ? m.api_keys_admin_action_suspend() : m.api_keys_action_suspend()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<!-- Revoke dialog -->
<Dialog.Root bind:open={showRevokeDialog}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>
        {isAdmin ? m.api_keys_admin_revoke_title() : m.api_keys_action_revoke_title()}
      </Dialog.Title>
      <Dialog.Description>
        {isAdmin ? m.api_keys_admin_revoke_description() : m.api_keys_action_revoke_description()}
      </Dialog.Description>
    </Dialog.Header>

    {#if errorMessage}
      <Alert.Root variant="destructive">
        <AlertCircle />
        <Alert.Description>{errorMessage}</Alert.Description>
      </Alert.Root>
    {/if}

    <Field.Field>
      <Field.Label for="revoke-reason">
        {isAdmin ? m.api_keys_admin_reason_optional() : m.api_keys_action_reason_optional()}
      </Field.Label>
      <Input id="revoke-reason" bind:value={reasonText} />
    </Field.Field>

    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>{m.cancel()}</Button>
        {/snippet}
      </Dialog.Close>
      <Button variant="destructive" onclick={revokeKey} disabled={actionPending}>
        {isAdmin ? m.api_keys_admin_action_revoke() : m.api_keys_action_revoke()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<RotateApiKeyDialog {apiKey} {mode} bind:open={showRotateDialog} {onSecret} />

<ExtendExpirationDialog {apiKey} {mode} bind:open={showExtendDialog} {onChanged} />

<AlertDialog.Root bind:open={showPurgeDialog}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.api_keys_purge_dialog_title()}</AlertDialog.Title>
      <AlertDialog.Description>
        {m.api_keys_purge_dialog_description()}
      </AlertDialog.Description>
    </AlertDialog.Header>
    <div class="bg-subtle border-default rounded-lg border p-3">
      <p class="text-default text-sm font-medium">{apiKey.name}</p>
      <p class="text-muted mt-0.5 font-mono text-xs">
        {apiKey.key_prefix}...{apiKey.key_suffix}
      </p>
    </div>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" onclick={purgeKey} disabled={actionPending}>
        {m.api_keys_purge_confirm()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
