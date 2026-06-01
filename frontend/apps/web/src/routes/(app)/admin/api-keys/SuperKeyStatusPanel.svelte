<script lang="ts">
  import { onMount } from "svelte";
  import { AlertCircle } from "lucide-svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import type { SuperApiKeyStatus } from "@intric/intric-js";
  import { getErrorMessage } from "$lib/core/errors/getErrorMessage";

  const intric = getIntric();

  let loading = $state(false);
  let errorMessage = $state<string | null>(null);
  let status = $state<SuperApiKeyStatus | null>(null);

  async function loadStatus() {
    loading = true;
    errorMessage = null;
    try {
      status = await intric.apiKeys.admin.getSuperKeyStatus();
    } catch (error) {
      console.error(error);
      errorMessage = getErrorMessage(error);
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
    <Alert.Root variant="destructive">
      <AlertCircle />
      <Alert.Description>{errorMessage}</Alert.Description>
    </Alert.Root>
  {/if}
  {#if loading}
    <div class="flex flex-col gap-3">
      <Skeleton class="h-12 w-full" />
      <Skeleton class="h-12 w-full" />
    </div>
  {/if}

  {#if status}
    <div class="flex flex-col gap-3">
      <div class="flex flex-col gap-1">
        <div class="flex items-center justify-between">
          <div class="text-sm font-medium">ENEO_SUPER_API_KEY</div>
          <Badge variant={status.super_api_key_configured ? "default" : "destructive"}>
            {status.super_api_key_configured
              ? m.api_keys_admin_status_configured()
              : m.api_keys_admin_status_not_configured()}
          </Badge>
        </div>
        {#if status.super_api_key_using_legacy}
          <p class="text-muted text-xs italic">
            {m.api_keys_admin_status_using_legacy({ newVar: "ENEO_SUPER_API_KEY" })}
          </p>
        {/if}
      </div>
      <div class="flex flex-col gap-1">
        <div class="flex items-center justify-between">
          <div class="text-sm font-medium">ENEO_SUPER_DUPER_API_KEY</div>
          <Badge variant={status.super_duper_api_key_configured ? "default" : "destructive"}>
            {status.super_duper_api_key_configured
              ? m.api_keys_admin_status_configured()
              : m.api_keys_admin_status_not_configured()}
          </Badge>
        </div>
        {#if status.super_duper_api_key_using_legacy}
          <p class="text-muted text-xs italic">
            {m.api_keys_admin_status_using_legacy({ newVar: "ENEO_SUPER_DUPER_API_KEY" })}
          </p>
        {/if}
      </div>
    </div>
    <p class="text-muted text-sm">
      {m.api_keys_admin_super_keys_info()}
    </p>
  {/if}
</div>
