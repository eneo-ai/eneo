<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@intric/intric-js";
  import {
    AlertCircle,
    Ban,
    Bell,
    BellOff,
    Eye,
    MoreVertical,
    Pencil,
    RefreshCw,
    RotateCcw
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
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";

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
  let actionPending = $state(false);
  let errorMessage = $state<string | null>(null);
  let reasonText = $state("");
  let followLoading = $state(false);
  let rotationGraceHours = $state(24);

  const isActive = $derived(apiKey.state === "active");
  const isSuspended = $derived(apiKey.state === "suspended");
  const canRotate = $derived(apiKey.state === "active");
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

  function formatLastUsed(lastUsedAt: string | null | undefined): string | null {
    if (!lastUsedAt) return null;
    const last = new Date(lastUsedAt);
    const now = new Date();
    const diffMs = now.getTime() - last.getTime();
    const diffMin = Math.floor(diffMs / 60_000);
    if (diffMin < 1) return m.api_keys_rotate_last_used_just_now();
    if (diffMin < 60) return m.api_keys_rotate_last_used_minutes({ minutes: diffMin });
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return m.api_keys_rotate_last_used_hours({ hours: diffHours });
    const diffDays = Math.floor(diffHours / 24);
    return m.api_keys_rotate_last_used_days({ days: diffDays });
  }

  async function openRotateDialog() {
    try {
      const constraints = await intric.apiKeys.getCreationConstraints();
      rotationGraceHours = constraints.rotation_grace_hours ?? 24;
    } catch {
      // Fall back to default
    }
    showRotateDialog = true;
  }

  async function rotateKey() {
    actionPending = true;
    try {
      const response = isAdmin
        ? await intric.apiKeys.admin.rotate({ id: apiKey.id })
        : await intric.apiKeys.rotate({ id: apiKey.id });
      if (!response?.secret) {
        throw new Error("rotate_missing_secret");
      }
      showRotateDialog = false;
      onSecret(response);
    } catch (error) {
      console.error(error);
      toast.error(getErrorMessage(error));
    } finally {
      actionPending = false;
    }
  }

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

{#if apiKey.state !== "revoked" || isAdmin}
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

      {#if isAdmin && onEditRequested}
        <DropdownMenu.Item onclick={onEditRequested}>
          <Pencil />
          {m.api_keys_admin_action_edit()}
        </DropdownMenu.Item>
      {/if}

      {#if canRotate}
        <DropdownMenu.Item onclick={openRotateDialog} disabled={!canManage}>
          <RotateCcw />
          {isAdmin ? m.api_keys_admin_action_rotate() : m.api_keys_action_rotate()}
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

<!-- Rotate confirmation dialog -->
<Dialog.Root bind:open={showRotateDialog}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>
        {m.api_keys_rotate_confirm_title()}
      </Dialog.Title>
      <Dialog.Description>
        {m.api_keys_rotate_confirm_description()}
      </Dialog.Description>
    </Dialog.Header>

    <div class="space-y-3">
      <div class="bg-subtle border-default rounded-lg border p-3">
        <p class="text-default text-sm font-medium">{apiKey.name}</p>
        <p class="text-muted mt-0.5 font-mono text-xs">
          {apiKey.key_prefix}...{apiKey.key_suffix}
        </p>
      </div>

      <div class="bg-subtle border-default space-y-1.5 rounded-lg border p-3">
        <div class="flex items-center justify-between">
          <span class="text-muted text-xs">{m.api_keys_rotate_grace_period_label()}</span>
          <span class="text-default text-sm font-medium">
            {m.api_keys_rotate_grace_period_value({ hours: rotationGraceHours })}
          </span>
        </div>
        {#if apiKey.last_used_at}
          {@const lastUsedText = formatLastUsed(apiKey.last_used_at)}
          {#if lastUsedText}
            <div class="flex items-center justify-between">
              <span class="text-muted text-xs">{m.api_keys_rotate_last_used_label()}</span>
              <span class="text-default text-sm">{lastUsedText}</span>
            </div>
          {/if}
        {/if}
        {#if apiKey.expires_at}
          <div class="flex items-center justify-between">
            <span class="text-muted text-xs">{m.api_keys_rotate_expires_label()}</span>
            <span class="text-default text-sm">
              {new Date(apiKey.expires_at).toLocaleDateString()}
            </span>
          </div>
        {/if}
      </div>

      <Alert.Root>
        <AlertCircle />
        <Alert.Description class="text-xs">
          {m.api_keys_rotate_grace_info({ hours: rotationGraceHours })}
        </Alert.Description>
      </Alert.Root>
    </div>

    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>{m.cancel()}</Button>
        {/snippet}
      </Dialog.Close>
      <Button onclick={rotateKey} disabled={actionPending}>
        {isAdmin ? m.api_keys_admin_action_rotate() : m.api_keys_action_rotate()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
