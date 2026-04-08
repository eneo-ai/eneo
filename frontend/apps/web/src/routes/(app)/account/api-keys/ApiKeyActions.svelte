<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@intric/intric-js";
  import { Ban, Bell, BellOff, MoreVertical, RefreshCw, RotateCcw } from "lucide-svelte";
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
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";

  const intric = getIntric();

  let {
    apiKey,
    onChanged,
    onSecret,
    isFollowed = false,
    isFollowedViaScope = false,
    onFollowChanged
  } = $props<{
    apiKey: ApiKeyV2;
    onChanged: () => void;
    onSecret: (response: ApiKeyCreatedResponse) => void;
    isFollowed?: boolean;
    isFollowedViaScope?: boolean;
    onFollowChanged?: () => void | Promise<void>;
  }>();

  let showRevokeDialog = $state(false);
  let showSuspendDialog = $state(false);
  let followLoading = $state(false);
  let actionPending = $state(false);
  let reasonText = $state("");

  const isActive = $derived(apiKey.state === "active");
  const isSuspended = $derived(apiKey.state === "suspended");
  const canRotate = $derived(apiKey.state === "active");

  async function rotateKey() {
    try {
      const response = await intric.apiKeys.rotate({ id: apiKey.id });
      if (!response?.secret) {
        throw new Error("rotate_missing_secret");
      }
      onSecret(response);
    } catch (error) {
      console.error(error);
      toast.error(getErrorMessage(error));
    }
  }

  async function revokeKey() {
    actionPending = true;
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
      toast.success(m.api_keys_action_revoke());
    } catch (error) {
      console.error(error);
      toast.error(getErrorMessage(error));
    } finally {
      actionPending = false;
    }
  }

  async function suspendKey() {
    actionPending = true;
    try {
      await intric.apiKeys.suspend({
        id: apiKey.id,
        request: {
          reason_code: "user_request",
          reason_text: reasonText || undefined
        }
      });
      onChanged();
      showSuspendDialog = false;
      reasonText = "";
      toast.success(m.api_keys_action_suspend());
    } catch (error) {
      console.error(error);
      toast.error(getErrorMessage(error));
    } finally {
      actionPending = false;
    }
  }

  async function reactivateKey() {
    try {
      await intric.apiKeys.reactivate({ id: apiKey.id });
      onChanged();
      toast.success(m.api_keys_action_reactivate());
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

{#if apiKey.state !== "revoked"}
  <DropdownMenu.Root>
    <DropdownMenu.Trigger>
      {#snippet child({ props })}
        <Button {...props} variant="ghost" size="icon" aria-label={m.actions()}>
          <MoreVertical />
        </Button>
      {/snippet}
    </DropdownMenu.Trigger>

    <DropdownMenu.Content align="end">
      {#if canRotate}
        <DropdownMenu.Item onclick={rotateKey}>
          <RotateCcw />
          {m.api_keys_action_rotate()}
        </DropdownMenu.Item>
      {/if}

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

      {#if isActive}
        <DropdownMenu.Item
          onclick={() => {
            showSuspendDialog = true;
          }}
        >
          <Ban />
          {m.api_keys_action_suspend()}
        </DropdownMenu.Item>
      {/if}

      {#if isSuspended}
        <DropdownMenu.Item onclick={reactivateKey}>
          <RefreshCw />
          {m.api_keys_action_reactivate()}
        </DropdownMenu.Item>
      {/if}

      <DropdownMenu.Separator />

      <DropdownMenu.Item
        variant="destructive"
        onclick={() => {
          showRevokeDialog = true;
        }}
      >
        <Ban />
        {m.api_keys_action_revoke()}
      </DropdownMenu.Item>
    </DropdownMenu.Content>
  </DropdownMenu.Root>
{/if}

<Dialog.Root bind:open={showSuspendDialog}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>{m.api_keys_action_suspend_title()}</Dialog.Title>
      <Dialog.Description>{m.api_keys_action_suspend_description()}</Dialog.Description>
    </Dialog.Header>

    <Field.Field>
      <Field.Label for="suspend-reason">{m.api_keys_action_reason_optional()}</Field.Label>
      <Input id="suspend-reason" bind:value={reasonText} />
    </Field.Field>

    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>{m.cancel()}</Button>
        {/snippet}
      </Dialog.Close>
      <Button variant="destructive" onclick={suspendKey} disabled={actionPending}>
        {m.api_keys_action_suspend()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>

<Dialog.Root bind:open={showRevokeDialog}>
  <Dialog.Content class="sm:max-w-md">
    <Dialog.Header>
      <Dialog.Title>{m.api_keys_action_revoke_title()}</Dialog.Title>
      <Dialog.Description>{m.api_keys_action_revoke_description()}</Dialog.Description>
    </Dialog.Header>

    <Field.Field>
      <Field.Label for="revoke-reason">{m.api_keys_action_reason_optional()}</Field.Label>
      <Input id="revoke-reason" bind:value={reasonText} />
    </Field.Field>

    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>{m.cancel()}</Button>
        {/snippet}
      </Dialog.Close>
      <Button variant="destructive" onclick={revokeKey} disabled={actionPending}>
        {m.api_keys_action_revoke()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
