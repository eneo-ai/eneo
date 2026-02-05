<script lang="ts">
  import { onMount } from "svelte";
  import { Label } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import type { SuperApiKeyStatus } from "@intric/intric-js";

  const intric = getIntric();

  let loading = $state(false);
  let errorMessage = $state<string | null>(null);
  let status = $state<SuperApiKeyStatus | null>(null);

  const statusLabel = (configured: boolean) => ({
    label: configured ? m.api_keys_admin_status_configured() : m.api_keys_admin_status_not_configured(),
    color: configured ? "green" : "red"
  });

  async function loadStatus() {
    loading = true;
    errorMessage = null;
    try {
      status = await intric.apiKeys.admin.getSuperKeyStatus();
    } catch (error) {
      console.error(error);
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    void loadStatus();
  });
</script>

<div class="flex flex-col gap-4">
  {#if errorMessage}
    <div class="text-sm text-red-600">{errorMessage}</div>
  {/if}
  {#if loading}
    <div class="text-muted text-sm">{m.loading()}</div>
  {/if}

  {#if status}
    <div class="flex flex-col gap-3">
      <div class="flex items-center justify-between">
        <div class="text-sm font-medium">INTRIC_SUPER_API_KEY</div>
        <Label.Single item={statusLabel(status.super_api_key_configured)} />
      </div>
      <div class="flex items-center justify-between">
        <div class="text-sm font-medium">INTRIC_SUPER_DUPER_API_KEY</div>
        <Label.Single item={statusLabel(status.super_duper_api_key_configured)} />
      </div>
    </div>
    <p class="text-muted text-sm">
      {m.api_keys_admin_super_keys_info()}
    </p>
  {/if}
</div>
