<script lang="ts">
  import { onMount } from "svelte";
  import { Page } from "$lib/components/layout";
  import { getAppContext } from "$lib/core/AppContext.js";
  import { getIntric } from "$lib/core/Intric";
  import { Button, CodeBlock, Dialog, Input } from "@intric/ui";
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";
  import ApiKeyTable from "./ApiKeyTable.svelte";
  import CreateApiKeyDialog from "./CreateApiKeyDialog.svelte";
  import {
    Key,
    AlertCircle,
    RefreshCw,
    Search,
    X,
    Copy,
    Check,
    ShieldAlert
  } from "lucide-svelte";
  import { fly, fade } from "svelte/transition";

  let mounted = $state(false);

  const {
    user,
    state: { userInfo }
  } = getAppContext();
  const intric = getIntric();

  let keys = $state<ApiKeyV2[]>([]);
  let loading = $state(false);
  let errorMessage = $state<string | null>(null);
  let searchQuery = $state("");
  let secretDialogOpen = $state<Dialog.OpenState>(undefined);
  let latestSecret = $state<string | null>(null);
  let copied = $state(false);

  async function loadKeys() {
    loading = true;
    errorMessage = null;
    try {
      const response = await intric.apiKeys.list({ limit: 100 });
      keys = response.items ?? [];
    } catch (error) {
      console.error(error);
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    } finally {
      loading = false;
    }
  }

  function handleSecret(response: ApiKeyCreatedResponse) {
    latestSecret = response.secret;
    secretDialogOpen = true;
    copied = false;
    void loadKeys();
  }

  function copyToClipboard() {
    if (latestSecret) {
      navigator.clipboard.writeText(latestSecret);
      copied = true;
      setTimeout(() => (copied = false), 2000);
    }
  }

  // Filter keys by search query
  const filteredKeys = $derived.by(() => {
    if (!searchQuery.trim()) return keys;
    const query = searchQuery.toLowerCase();
    return keys.filter(
      (key) =>
        key.name.toLowerCase().includes(query) ||
        key.key_suffix?.toLowerCase().includes(query) ||
        key.description?.toLowerCase().includes(query)
    );
  });

  onMount(() => {
    mounted = true;
    void loadKeys();
  });
</script>

<svelte:head>
  <title>Eneo.ai – Account – {$userInfo.firstName}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.my_api_keys()}>
      <div slot="actions" class="flex items-center gap-3">
        <Button variant="ghost" on:click={loadKeys} class="gap-2">
          <RefreshCw class="h-4 w-4 {loading ? 'animate-spin' : ''}" />
          {m.api_keys_refresh()}
        </Button>
        <CreateApiKeyDialog onCreated={handleSecret} />
      </div>
    </Page.Title>
  </Page.Header>

  <Page.Main>
    <div class="space-y-6 pr-4 py-4">
      <!-- Header section with info and search -->
      {#if mounted}
        <div
          class="rounded-xl border border-default bg-primary shadow-sm overflow-hidden"
          in:fly={{ y: 16, duration: 300, delay: 0 }}
        >
          <div class="px-6 py-5 bg-gradient-to-r from-accent-default/8 via-accent-default/3 to-transparent dark:from-accent-default/10 dark:via-accent-default/5 dark:to-transparent border-b border-default">
          <div class="flex items-start gap-4">
            <div class="flex h-12 w-12 items-center justify-center rounded-xl bg-accent-default/10 flex-shrink-0">
              <Key class="h-6 w-6 text-accent-default" />
            </div>
            <div class="flex-1">
              <h2 class="text-lg font-semibold text-default">{m.api_keys_your_keys()}</h2>
              <p class="mt-1 text-sm text-muted max-w-2xl">
                {m.api_keys_description()}
              </p>
            </div>
            <!-- Create button in header for visibility -->
            <div class="hidden lg:block flex-shrink-0">
              <CreateApiKeyDialog onCreated={handleSecret} />
            </div>
          </div>
        </div>

        <!-- Search bar -->
        {#if keys.length > 0}
          <div class="px-6 py-4 bg-subtle/20">
            <div class="relative max-w-md">
              <Search class="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted pointer-events-none" />
              <Input.Text
                bind:value={searchQuery}
                placeholder={m.api_keys_search_placeholder()}
                class="!pl-10 !h-10 !bg-primary !border-default/60 focus:!border-accent-default/50"
              />
              {#if searchQuery}
                <button
                  type="button"
                  onclick={() => (searchQuery = "")}
                  class="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded-md hover:bg-hover text-muted hover:text-default transition-colors"
                >
                  <X class="h-4 w-4" />
                </button>
              {/if}
            </div>
          </div>
        {/if}
        </div>
      {/if}

      <!-- Error Message -->
      {#if errorMessage}
        <div
          class="flex items-center gap-3 rounded-xl border border-negative/30 bg-negative/5 px-5 py-4"
          transition:fly={{ y: -8, duration: 150 }}
        >
          <AlertCircle class="h-5 w-5 text-negative flex-shrink-0" />
          <p class="text-sm text-negative">{errorMessage}</p>
        </div>
      {/if}

      <!-- Legacy key notice - only show when no v2 keys exist -->
      {#if user.truncated_api_key && keys.length === 0 && !loading && mounted}
        <div
          class="rounded-xl border border-caution/30 bg-caution/5 dark:bg-caution/10 p-5"
          in:fly={{ y: 16, duration: 300, delay: 100 }}
        >
          <div class="flex items-start gap-4">
            <div class="flex h-10 w-10 items-center justify-center rounded-lg bg-caution/15 dark:bg-caution/20 flex-shrink-0">
              <ShieldAlert class="h-5 w-5 text-caution" />
            </div>
            <div class="flex-1">
              <h3 class="font-semibold text-caution">{m.api_keys_legacy_detected()}</h3>
              <p class="mt-1 text-sm text-muted">
                {m.api_keys_legacy_ending_in()} <code class="font-mono bg-caution/15 dark:bg-caution/20 px-1.5 py-0.5 rounded text-caution">****{user.truncated_api_key}</code>.
                {m.api_keys_legacy_recommend()}
              </p>
              <div class="mt-3">
                <CreateApiKeyDialog onCreated={handleSecret} />
              </div>
            </div>
          </div>
        </div>
      {/if}

      <!-- Keys Table -->
      {#if mounted}
        <div
          class="rounded-xl border border-default bg-primary shadow-sm overflow-hidden"
          in:fly={{ y: 16, duration: 300, delay: 150 }}
        >
          <div class="px-6 py-4 border-b border-default bg-subtle/30">
          <div class="flex items-center justify-between">
            <div>
              <h3 class="font-semibold text-default">
                {filteredKeys.length === keys.length
                  ? (keys.length !== 1 ? m.api_keys_count_plural({ count: keys.length }) : m.api_keys_count({ count: keys.length }))
                  : m.api_keys_filtered({ filtered: filteredKeys.length, total: keys.length })}
              </h3>
              <p class="text-xs text-muted mt-0.5">
                {loading ? m.api_keys_loading() : m.api_keys_click_to_view()}
              </p>
            </div>
            <!-- Mobile create button -->
            <div class="lg:hidden">
              <CreateApiKeyDialog onCreated={handleSecret} />
            </div>
          </div>
        </div>

        <div class="p-4">
          <ApiKeyTable
            keys={filteredKeys}
            {loading}
            onChanged={loadKeys}
            onSecret={handleSecret}
          />
        </div>
        </div>
      {/if}
    </div>
  </Page.Main>
</Page.Root>

<!-- Secret Key Dialog -->
<Dialog.Root bind:isOpen={secretDialogOpen} alert>
  <Dialog.Content width="medium">
    <Dialog.Title class="flex items-center gap-3">
      <div class="flex h-10 w-10 items-center justify-center rounded-xl bg-positive/10 dark:bg-positive/15">
        <Key class="h-5 w-5 text-positive" />
      </div>
      <span class="text-default">{m.api_keys_created_title()}</span>
    </Dialog.Title>
    <Dialog.Description>
      <div class="mt-3 flex items-start gap-3 rounded-lg border border-caution/30 bg-caution/5 dark:bg-caution/10 px-4 py-3">
        <AlertCircle class="h-5 w-5 text-caution flex-shrink-0 mt-0.5" />
        <div class="text-sm text-muted">
          <strong class="text-caution">{m.api_keys_important()}</strong> {m.api_keys_copy_warning()}
        </div>
      </div>
    </Dialog.Description>
    {#if latestSecret}
      <div class="mt-5">
        <span class="block text-sm font-medium text-muted mb-2">{m.api_keys_your_new_key()}</span>
        <div class="relative">
          <CodeBlock code={latestSecret} />
        </div>
        <div class="mt-4 flex items-center gap-3">
          <Button
            variant={copied ? "outlined" : "primary"}
            on:click={copyToClipboard}
            class="gap-2 transition-all duration-200 {copied ? '!bg-positive/10 !border-positive/30 !text-positive' : ''}"
          >
            {#if copied}
              <span in:fly={{ y: -8, duration: 150 }}>
                <Check class="h-4 w-4" />
              </span>
              <span in:fly={{ y: 8, duration: 150 }}>{m.api_keys_copied()}</span>
            {:else}
              <Copy class="h-4 w-4" />
              {m.api_keys_copy_to_clipboard()}
            {/if}
          </Button>
          {#if copied}
            <span
              class="text-sm text-positive"
              in:fade={{ duration: 150 }}
              out:fade={{ duration: 150 }}
            >
              {m.api_keys_copied_message()}
            </span>
          {/if}
        </div>
      </div>
    {/if}
    <Dialog.Controls let:close>
      <Button is={close} variant="outlined">{m.close()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
