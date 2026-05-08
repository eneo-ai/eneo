<script lang="ts">
  import type { ApiKeyV2 } from "@intric/intric-js";
  import { AlertCircle, Calendar, Infinity as InfinityIcon } from "lucide-svelte";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { toast } from "svelte-sonner";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import ExpirationPicker from "$lib/features/api-keys/ExpirationPicker.svelte";

  const intric = getIntric();

  let {
    apiKey,
    mode = "user",
    open = $bindable(false),
    onChanged
  }: {
    apiKey: ApiKeyV2;
    mode?: "user" | "admin";
    open?: boolean;
    onChanged: () => void;
  } = $props();

  // Initialised on open via the $effect below — keeping it null here avoids
  // capturing the initial $props value statically (state_referenced_locally).
  let pickerValue = $state<string | null>(null);
  let maxDays = $state<number | null>(null);
  let requireExpiration = $state(false);
  let constraintsLoaded = $state(false);
  let saving = $state(false);
  let errorMessage = $state<string | null>(null);

  $effect(() => {
    if (open) {
      pickerValue = apiKey.expires_at ?? null;
      errorMessage = null;
      void loadConstraints();
    }
  });

  async function loadConstraints() {
    try {
      const constraints = await intric.apiKeys.getPolicyConstraints();
      maxDays = constraints.max_expiration_days ?? null;
      requireExpiration = constraints.require_expiration ?? false;
    } catch (error) {
      console.error(error);
    } finally {
      constraintsLoaded = true;
    }
  }

  const hasChange = $derived((apiKey.expires_at ?? null) !== (pickerValue ?? null));

  function formatDate(value: string | null): string {
    if (!value) return m.api_keys_extend_summary_no_expiration();
    const locale = getLocale();
    return new Date(value).toLocaleDateString(locale === "sv" ? "sv-SE" : "en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  async function save() {
    if (!hasChange || saving) return;
    saving = true;
    errorMessage = null;
    try {
      const params = { id: apiKey.id, expires_at: pickerValue };
      if (mode === "admin") {
        await intric.apiKeys.admin.extend(params);
      } else {
        await intric.apiKeys.extend(params);
      }
      onChanged();
      open = false;
      toast.success(m.api_keys_extend_apply());
    } catch (error) {
      console.error(error);
      errorMessage = getErrorMessage(error);
    } finally {
      saving = false;
    }
  }
</script>

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title>{m.api_keys_extend_dialog_title()}</Dialog.Title>
      <Dialog.Description>{m.api_keys_extend_dialog_description()}</Dialog.Description>
    </Dialog.Header>

    {#if errorMessage}
      <Alert.Root variant="destructive">
        <AlertCircle />
        <Alert.Description>{errorMessage}</Alert.Description>
      </Alert.Root>
    {/if}

    <div class="bg-subtle border-default rounded-lg border p-3">
      <p class="text-default text-sm font-medium">{apiKey.name}</p>
      <p class="text-muted mt-0.5 font-mono text-xs">
        {apiKey.key_prefix}...{apiKey.key_suffix}
      </p>
    </div>

    <div class="border-default grid gap-3 rounded-lg border p-3 sm:grid-cols-2">
      <div class="flex items-start gap-2">
        <div class="bg-subtle flex h-7 w-7 items-center justify-center rounded-md">
          {#if apiKey.expires_at}
            <Calendar class="text-muted h-3.5 w-3.5" />
          {:else}
            <InfinityIcon class="text-muted h-3.5 w-3.5" />
          {/if}
        </div>
        <div class="min-w-0">
          <p class="text-muted text-xs">{m.api_keys_extend_summary_previous()}</p>
          <p class="text-default truncate text-sm font-medium">
            {formatDate(apiKey.expires_at ?? null)}
          </p>
        </div>
      </div>
      <div class="flex items-start gap-2">
        <div class="bg-accent-default/15 flex h-7 w-7 items-center justify-center rounded-md">
          {#if pickerValue}
            <Calendar class="text-accent-default h-3.5 w-3.5" />
          {:else}
            <InfinityIcon class="text-accent-default h-3.5 w-3.5" />
          {/if}
        </div>
        <div class="min-w-0">
          <p class="text-muted text-xs">{m.api_keys_extend_summary_new()}</p>
          <p class="text-default truncate text-sm font-medium">{formatDate(pickerValue)}</p>
        </div>
      </div>
    </div>

    {#if constraintsLoaded}
      <ExpirationPicker bind:value={pickerValue} {maxDays} {requireExpiration} disabled={saving} />
    {/if}

    {#if !hasChange}
      <p class="text-muted text-xs">{m.api_keys_extend_no_change_hint()}</p>
    {/if}

    <Dialog.Footer>
      <Dialog.Close>
        {#snippet child({ props })}
          <Button variant="outline" {...props}>{m.cancel()}</Button>
        {/snippet}
      </Dialog.Close>
      <Button onclick={save} disabled={!hasChange || saving}>
        {m.api_keys_extend_apply()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
