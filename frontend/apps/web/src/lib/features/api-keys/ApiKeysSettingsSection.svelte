<script lang="ts">
  import { onMount } from "svelte";
  import { writable } from "svelte/store";
  import type { ApiKeyCreatedResponse, ApiKeyScopeType, ApiKeyV2 } from "@intric/intric-js";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "@intric/ui";
  import { Key, ChevronDown, AlertCircle, ExternalLink, RefreshCw } from "lucide-svelte";
  import { slide } from "svelte/transition";
  import ApiKeyTable from "../../../routes/(app)/account/api-keys/ApiKeyTable.svelte";
  import CreateApiKeyDialog from "../../../routes/(app)/account/api-keys/CreateApiKeyDialog.svelte";
  import ApiKeySecretDialog from "../../../routes/(app)/account/api-keys/ApiKeySecretDialog.svelte";

  const intric = getIntric();

  let {
    scopeType,
    scopeId,
    scopeName
  }: {
    scopeType: ApiKeyScopeType;
    scopeId: string;
    scopeName: string;
  } = $props();

  let keys = $state<ApiKeyV2[]>([]);
  let loading = $state(false);
  let errorMessage = $state<string | null>(null);
  let expanded = $state(false);

  // Secret dialog state
  const secretDialogOpen = writable(false);
  let latestSecret = $state<string | null>(null);
  let secretSource = $state<"created" | "rotated">("created");

  // Computed stats
  const activeCount = $derived(keys.filter((k) => k.state === "active").length);
  const suspendedCount = $derived(keys.filter((k) => k.state === "suspended").length);

  async function loadKeys() {
    loading = true;
    errorMessage = null;
    try {
      const response = await intric.apiKeys.list({
        scope_type: scopeType,
        scope_id: scopeId,
        limit: 20
      });
      keys = response.items ?? [];
    } catch (error) {
      console.error(error);
      const err = error as { getReadableMessage?: () => string };
      errorMessage = err?.getReadableMessage?.() ?? m.api_keys_load_error();
    } finally {
      loading = false;
    }
  }

  function handleSecret(response: ApiKeyCreatedResponse) {
    latestSecret = response.secret;
    secretSource = "rotated";
    secretDialogOpen.set(true);
    void loadKeys();
  }

  function handleCreated() {
    secretDialogOpen.set(false);
    latestSecret = null;
    void loadKeys();
  }

  function getEmptyMessage(): string {
    switch (scopeType) {
      case "assistant": return m.api_keys_empty_assistant();
      case "space": return m.api_keys_empty_space();
      case "app": return m.api_keys_empty_app();
      default: return m.api_keys_empty_assistant();
    }
  }

  onMount(() => {
    void loadKeys();
  });
</script>

<div class="w-full">
  {#if errorMessage}
    <!-- Error state -->
    <div class="flex items-center gap-3 rounded-lg border border-negative-default/20 bg-negative-dimmer px-5 py-4">
      <AlertCircle class="h-4 w-4 text-negative-default flex-shrink-0" />
      <p class="flex-1 text-sm text-negative-default">{errorMessage}</p>
      <Button variant="ghost" on:click={loadKeys} class="gap-1.5 text-xs">
        <RefreshCw class="h-3.5 w-3.5" />
        {m.retry()}
      </Button>
    </div>
  {:else if loading && keys.length === 0}
    <!-- Loading state -->
    <div class="flex items-center gap-3 py-4">
      <div class="h-4 w-4 animate-spin rounded-full border-2 border-accent-default border-t-transparent"></div>
      <span class="text-sm text-muted">{m.loading()}...</span>
    </div>
  {:else if keys.length === 0}
    <!-- Empty state -->
    <div class="flex items-start gap-4 rounded-lg border border-default px-5 py-5">
      <Key class="mt-0.5 h-5 w-5 flex-shrink-0 text-muted" />
      <div class="flex flex-col gap-3">
        <p class="text-sm leading-relaxed text-secondary">{getEmptyMessage()}</p>
        <div>
          <CreateApiKeyDialog
            onCreated={handleCreated}
            lockedScopeType={scopeType}
            lockedScopeId={scopeId}
            lockedScopeName={scopeName}
            triggerVariant="outlined"
          />
        </div>
      </div>
    </div>
  {:else}
    <!-- Collapsible key list -->
    <div class="overflow-hidden rounded-lg border border-default">
      <!-- Summary header -->
      <button
        type="button"
        onclick={() => (expanded = !expanded)}
        class="flex w-full items-center justify-between px-5 py-4 text-left transition-colors hover:bg-hover-dimmer"
        aria-expanded={expanded}
      >
        <div class="flex items-center gap-3">
          <Key class="h-4 w-4 text-muted" />
          <span class="text-sm font-medium text-default">
            {keys.length} {m.api_keys()}
          </span>
          <span class="text-xs text-muted">
            {m.api_keys_summary({ active: activeCount, suspended: suspendedCount })}
          </span>
        </div>
        <ChevronDown
          class="h-4 w-4 text-muted transition-transform duration-200 {expanded ? 'rotate-180' : ''}"
        />
      </button>

      <!-- Expanded content -->
      {#if expanded}
        <div transition:slide={{ duration: 200 }}>
          <div class="border-t border-default px-5 py-5">
            <ApiKeyTable
              {keys}
              {loading}
              onChanged={loadKeys}
              onSecret={handleSecret}
            />
          </div>
        </div>
      {/if}

      <!-- Footer actions -->
      <div class="flex items-center justify-between border-t border-dimmer px-5 py-3">
        <CreateApiKeyDialog
          onCreated={handleCreated}
          lockedScopeType={scopeType}
          lockedScopeId={scopeId}
          lockedScopeName={scopeName}
          triggerVariant="outlined"
        />
        <a
          href="/account/api-keys"
          class="flex items-center gap-1.5 text-xs text-secondary transition-colors hover:text-default"
        >
          {m.api_keys_manage_all()}
          <ExternalLink class="h-3 w-3" />
        </a>
      </div>
    </div>
  {/if}
</div>

<ApiKeySecretDialog
  openController={secretDialogOpen}
  secret={latestSecret}
  source={secretSource}
/>
