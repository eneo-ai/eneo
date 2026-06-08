<script lang="ts">
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@intric/intric-js";
  import { AlertCircle } from "lucide-svelte";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "svelte-sonner";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import ExpirationPicker from "$lib/features/api-keys/ExpirationPicker.svelte";

  const intric = getIntric();

  let {
    apiKey,
    mode = "user",
    open = $bindable(false),
    onSecret
  }: {
    apiKey: ApiKeyV2;
    mode?: "user" | "admin";
    open?: boolean;
    onSecret: (response: ApiKeyCreatedResponse) => void;
  } = $props();

  let rotationGraceHours = $state(24);
  let alsoExtend = $state(false);
  let disableGracePeriod = $state(false);
  let newExpiresAt = $state<string | null>(null);
  let maxDays = $state<number | null>(null);
  let requireExpiration = $state(false);
  let actionPending = $state(false);

  const isAdmin = $derived(mode === "admin");

  $effect(() => {
    if (open) {
      alsoExtend = false;
      disableGracePeriod = false;
      newExpiresAt = apiKey.expires_at ?? null;
      void loadConstraints();
    }
  });

  async function loadConstraints() {
    try {
      const constraints = await intric.apiKeys.getPolicyConstraints();
      rotationGraceHours = constraints.rotation_grace_hours ?? 24;
      maxDays = constraints.max_expiration_days ?? null;
      requireExpiration = constraints.require_expiration ?? false;
    } catch {
      // Fall back to defaults
    }
  }

  function formatLastUsed(lastUsedAt: string | null | undefined): string | null {
    if (!lastUsedAt) return null;
    const last = new Date(lastUsedAt);
    const diffMin = Math.floor((Date.now() - last.getTime()) / 60_000);
    if (diffMin < 1) return m.api_keys_rotate_last_used_just_now();
    if (diffMin < 60) return m.api_keys_rotate_last_used_minutes({ minutes: diffMin });
    const diffHours = Math.floor(diffMin / 60);
    if (diffHours < 24) return m.api_keys_rotate_last_used_hours({ hours: diffHours });
    const diffDays = Math.floor(diffHours / 24);
    return m.api_keys_rotate_last_used_days({ days: diffDays });
  }

  async function rotate() {
    actionPending = true;
    try {
      const params: {
        id: string;
        update_expiration?: boolean;
        expires_at?: string | null;
        disable_grace_period?: boolean;
      } = { id: apiKey.id };
      if (alsoExtend) {
        params.update_expiration = true;
        params.expires_at = newExpiresAt;
      }
      if (disableGracePeriod) {
        params.disable_grace_period = true;
      }
      const response = isAdmin
        ? await intric.apiKeys.admin.rotate(params)
        : await intric.apiKeys.rotate(params);
      if (!response?.secret) {
        throw new Error("rotate_missing_secret");
      }
      open = false;
      onSecret(response);
    } catch (error) {
      console.error(error);
      toast.error(getErrorMessage(error));
    } finally {
      actionPending = false;
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title>{m.api_keys_rotate_confirm_title()}</Dialog.Title>
      <Dialog.Description>{m.api_keys_rotate_confirm_description()}</Dialog.Description>
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
            {#if disableGracePeriod}
              {m.api_keys_rotate_grace_period_disabled_value()}
            {:else}
              {m.api_keys_rotate_grace_period_value({ hours: rotationGraceHours })}
            {/if}
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

        <Alert.Root class="mt-2" variant={disableGracePeriod ? "destructive" : "default"}>
          <AlertCircle />
          <Alert.Description class="text-xs">
            {#if disableGracePeriod}
              {m.api_keys_rotate_disable_grace_warning()}
            {:else}
              {m.api_keys_rotate_grace_info({ hours: rotationGraceHours })}
            {/if}
          </Alert.Description>
        </Alert.Root>

        <label class="border-default mt-3 flex items-start gap-2 border-t pt-3 text-sm">
          <Checkbox
            class="mt-0.5"
            checked={disableGracePeriod}
            disabled={actionPending}
            onCheckedChange={(v) => (disableGracePeriod = v === true)}
          />
          <span>
            <span class="text-default block font-medium">
              {m.api_keys_rotate_disable_grace_label()}
            </span>
            <span class="text-muted block text-xs">
              {m.api_keys_rotate_disable_grace_help()}
            </span>
          </span>
        </label>
      </div>

      <div class="space-y-2">
        <label class="flex items-center gap-2 text-sm">
          <Checkbox
            checked={alsoExtend}
            disabled={actionPending}
            onCheckedChange={(v) => (alsoExtend = v === true)}
          />
          <span>{m.api_keys_rotate_also_extend_label()}</span>
        </label>

        {#if alsoExtend}
          <ExpirationPicker
            bind:value={newExpiresAt}
            {maxDays}
            {requireExpiration}
            disabled={actionPending}
          />
        {/if}
      </div>
    </div>

    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>{m.cancel()}</Button>
        {/snippet}
      </Dialog.Close>
      <Button onclick={rotate} disabled={actionPending}>
        {isAdmin ? m.api_keys_admin_action_rotate() : m.api_keys_action_rotate()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
