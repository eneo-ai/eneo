<script lang="ts">
  import { onMount } from "svelte";
  import { Page, Settings } from "$lib/components/layout";
  import { Button, CodeBlock, Dialog, Input, Select, Label } from "@intric/ui";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import type { ApiKeyCreatedResponse, ApiKeyV2 } from "@intric/intric-js";
  import AdminApiKeyTable from "./AdminApiKeyTable.svelte";
  import ApiKeyPolicyPanel from "./ApiKeyPolicyPanel.svelte";
  import SuperKeyStatusPanel from "./SuperKeyStatusPanel.svelte";
  import {
    Search,
    Filter,
    X,
    Key,
    AlertCircle,
    ChevronDown,
    RefreshCw,
    Building2,
    Shield,
    Lock,
    Globe
  } from "lucide-svelte";
  import { fly, slide } from "svelte/transition";

  const intric = getIntric();

  let keys = $state<ApiKeyV2[]>([]);
  let loading = $state(false);
  let loadingMore = $state(false);
  let errorMessage = $state<string | null>(null);
  let nextCursor = $state<string | null>(null);
  let totalCount = $state<number | null>(null);

  // Filter states
  let scopeType = $state("");
  let stateFilter = $state("");
  let keyType = $state("");
  let scopeId = $state("");
  let createdByUserId = $state("");
  let limit = $state("100");
  let searchQuery = $state("");

  // UI states
  let showFilters = $state(true);
  let secretDialogOpen: Dialog.OpenState;
  let latestSecret = $state<string | null>(null);

  // Quick filter chips
  const quickFilters = [
    { label: "Active", filter: { state: "active" }, color: "green" as const },
    { label: "Suspended", filter: { state: "suspended" }, color: "yellow" as const },
    { label: "Expired", filter: { state: "expired" }, color: "gray" as const },
    { label: "Secret keys", filter: { keyType: "sk_" }, color: "blue" as const },
    { label: "Public keys", filter: { keyType: "pk_" }, color: "orange" as const }
  ];

  const scopeOptions = [
    { value: "", label: "All scopes" },
    { value: "tenant", label: "Tenant" },
    { value: "space", label: "Space" },
    { value: "assistant", label: "Assistant" },
    { value: "app", label: "App" }
  ];

  const stateOptions = [
    { value: "", label: "All states" },
    { value: "active", label: "Active" },
    { value: "suspended", label: "Suspended" },
    { value: "revoked", label: "Revoked" },
    { value: "expired", label: "Expired" }
  ];

  const keyTypeOptions = [
    { value: "", label: "All types" },
    { value: "pk_", label: "Public (pk_)" },
    { value: "sk_", label: "Secret (sk_)" }
  ];

  // Active filter count
  const activeFilterCount = $derived(
    [scopeType, stateFilter, keyType, scopeId.trim(), createdByUserId.trim()].filter(Boolean).length
  );

  function parseLimit() {
    const parsed = Number(limit);
    return Number.isNaN(parsed) || parsed <= 0 ? undefined : parsed;
  }

  function buildParams(cursor?: string | null) {
    const params: Record<string, unknown> = {};
    const parsedLimit = parseLimit();
    if (parsedLimit) params.limit = parsedLimit;
    if (cursor) params.cursor = cursor;
    if (scopeType) params.scope_type = scopeType;
    if (stateFilter) params.state = stateFilter;
    if (keyType) params.key_type = keyType;
    if (scopeId.trim()) params.scope_id = scopeId.trim();
    if (createdByUserId.trim()) params.created_by_user_id = createdByUserId.trim();
    return params;
  }

  async function loadKeys({ reset }: { reset: boolean }) {
    if (reset) {
      loading = true;
      errorMessage = null;
    } else {
      loadingMore = true;
    }

    try {
      const response = await intric.apiKeys.admin.list(
        buildParams(reset ? null : nextCursor)
      );
      const items = response.items ?? [];
      keys = reset ? items : [...keys, ...items];
      nextCursor = response.next_cursor ?? null;
      totalCount = response.total_count ?? null;
    } catch (error) {
      console.error(error);
      errorMessage = error?.getReadableMessage?.() ?? m.something_went_wrong();
    } finally {
      loading = false;
      loadingMore = false;
    }
  }

  function applyFilters() {
    void loadKeys({ reset: true });
  }

  function resetFilters() {
    scopeType = "";
    stateFilter = "";
    keyType = "";
    scopeId = "";
    createdByUserId = "";
    limit = "100";
    void loadKeys({ reset: true });
  }

  function applyQuickFilter(filter: { state?: string; keyType?: string }) {
    if (filter.state) {
      stateFilter = stateFilter === filter.state ? "" : filter.state;
    }
    if (filter.keyType) {
      keyType = keyType === filter.keyType ? "" : filter.keyType;
    }
    void loadKeys({ reset: true });
  }

  function isQuickFilterActive(filter: { state?: string; keyType?: string }): boolean {
    if (filter.state) return stateFilter === filter.state;
    if (filter.keyType) return keyType === filter.keyType;
    return false;
  }

  function handleSecret(response: ApiKeyCreatedResponse) {
    latestSecret = response.secret;
    secretDialogOpen = true;
    void loadKeys({ reset: true });
  }

  // Filter keys by search query (client-side)
  const filteredKeys = $derived.by(() => {
    if (!searchQuery.trim()) return keys;
    const query = searchQuery.toLowerCase();
    return keys.filter(
      (key) =>
        key.name.toLowerCase().includes(query) ||
        key.key_suffix?.toLowerCase().includes(query) ||
        key.scope_id?.toLowerCase().includes(query)
    );
  });

  onMount(() => {
    void loadKeys({ reset: true });
  });
</script>

<svelte:head>
  <title>Eneo.ai – {m.admin()} – {m.api_keys()}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title title={m.api_keys()}>
      <div slot="actions" class="flex items-center gap-3">
        <Button variant="ghost" on:click={() => loadKeys({ reset: true })} class="gap-2">
          <RefreshCw class="h-4 w-4 {loading ? 'animate-spin' : ''}" />
          Refresh
        </Button>
      </div>
    </Page.Title>
  </Page.Header>

  <Page.Main>
    <div class="space-y-6">
      <!-- Filter Section -->
      <div class="rounded-xl border border-default bg-primary shadow-sm overflow-hidden">
        <!-- Filter Header -->
        <button
          type="button"
          onclick={() => (showFilters = !showFilters)}
          class="w-full flex items-center justify-between px-6 py-4 bg-subtle/50 hover:bg-subtle transition-colors"
        >
          <div class="flex items-center gap-3">
            <div class="flex h-9 w-9 items-center justify-center rounded-lg bg-primary border border-default">
              <Filter class="h-4 w-4 text-muted" />
            </div>
            <div class="text-left">
              <h3 class="font-semibold text-default text-sm">Filters & Search</h3>
              <p class="text-xs text-muted">
                {activeFilterCount > 0
                  ? `${activeFilterCount} filter${activeFilterCount > 1 ? "s" : ""} active`
                  : "Filter API keys by scope, state, or creator"}
              </p>
            </div>
            {#if activeFilterCount > 0}
              <span class="inline-flex items-center justify-center h-5 w-5 rounded-full bg-accent-default text-on-fill text-xs font-bold">
                {activeFilterCount}
              </span>
            {/if}
          </div>
          <ChevronDown class="h-5 w-5 text-muted transition-transform duration-200 {showFilters ? 'rotate-180' : ''}" />
        </button>

        <!-- Filter Content -->
        {#if showFilters}
          <div transition:slide={{ duration: 200 }} class="px-6 py-5 border-t border-default space-y-5">
            <!-- Search -->
            <div class="relative">
              <Search class="absolute left-3.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted pointer-events-none" />
              <Input.Text
                bind:value={searchQuery}
                placeholder="Search by name, key suffix, or scope ID..."
                class="!pl-10 !h-11"
              />
              {#if searchQuery}
                <button
                  type="button"
                  onclick={() => (searchQuery = "")}
                  class="absolute right-3 top-1/2 -translate-y-1/2 p-1 rounded hover:bg-hover text-muted hover:text-default transition-colors"
                >
                  <X class="h-4 w-4" />
                </button>
              {/if}
            </div>

            <!-- Quick Filters -->
            <div class="flex flex-wrap gap-2">
              {#each quickFilters as qf}
                {@const isActive = isQuickFilterActive(qf.filter)}
                <button
                  type="button"
                  onclick={() => applyQuickFilter(qf.filter)}
                  class="inline-flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium transition-all
                         {isActive
                    ? 'border-accent-default bg-accent-default/10 text-accent-default ring-2 ring-accent-default/20'
                    : 'border-default bg-primary text-muted hover:border-dimmer hover:text-default'}"
                >
                  {#if qf.filter.keyType === "sk_"}
                    <Lock class="h-3 w-3" />
                  {:else if qf.filter.keyType === "pk_"}
                    <Globe class="h-3 w-3" />
                  {:else}
                    <span
                      class="h-2 w-2 rounded-full
                             {qf.color === 'green' ? 'bg-green-500' : ''}
                             {qf.color === 'yellow' ? 'bg-yellow-500' : ''}
                             {qf.color === 'gray' ? 'bg-gray-500' : ''}
                             {qf.color === 'blue' ? 'bg-blue-500' : ''}
                             {qf.color === 'orange' ? 'bg-orange-500' : ''}"
                    ></span>
                  {/if}
                  {qf.label}
                  {#if isActive}
                    <X class="h-3 w-3" />
                  {/if}
                </button>
              {/each}
            </div>

            <!-- Advanced Filters -->
            <div class="grid gap-4 md:grid-cols-3">
              <Select.Simple bind:value={scopeType} options={scopeOptions} resourceName="scope">
                Scope type
              </Select.Simple>
              <Select.Simple bind:value={stateFilter} options={stateOptions} resourceName="state">
                State
              </Select.Simple>
              <Select.Simple bind:value={keyType} options={keyTypeOptions} resourceName="key type">
                Key type
              </Select.Simple>
            </div>

            <div class="grid gap-4 md:grid-cols-3">
              <Input.Text bind:value={scopeId} label="Scope ID" placeholder="UUID" />
              <Input.Text bind:value={createdByUserId} label="Created by user ID" placeholder="UUID" />
              <Input.Text bind:value={limit} label="Results limit" placeholder="100" />
            </div>

            <!-- Filter Actions -->
            <div class="flex items-center justify-between pt-2 border-t border-default">
              <p class="text-xs text-muted">
                {totalCount !== null ? `${filteredKeys.length} of ${totalCount} keys` : ""}
              </p>
              <div class="flex items-center gap-2">
                <Button variant="ghost" on:click={resetFilters} class="text-sm">
                  <X class="h-4 w-4 mr-1.5" />
                  Clear all
                </Button>
                <Button variant="primary" on:click={applyFilters} class="text-sm">
                  <Filter class="h-4 w-4 mr-1.5" />
                  Apply filters
                </Button>
              </div>
            </div>
          </div>
        {/if}
      </div>

      <!-- Error Message -->
      {#if errorMessage}
        <div
          class="flex items-center gap-3 rounded-xl border border-red-200 bg-red-50 px-5 py-4 dark:border-red-900 dark:bg-red-950/50"
          transition:fly={{ y: -8, duration: 150 }}
        >
          <AlertCircle class="h-5 w-5 text-red-600 dark:text-red-400 flex-shrink-0" />
          <p class="text-sm text-red-700 dark:text-red-300">{errorMessage}</p>
        </div>
      {/if}

      <!-- Keys Table Section -->
      <div class="rounded-xl border border-default bg-primary shadow-sm overflow-hidden">
        <div class="px-6 py-4 border-b border-default bg-subtle/30">
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-3">
              <div class="flex h-10 w-10 items-center justify-center rounded-xl bg-accent-default/10">
                <Key class="h-5 w-5 text-accent-default" />
              </div>
              <div>
                <h3 class="font-semibold text-default">API Keys</h3>
                <p class="text-xs text-muted">
                  {totalCount !== null
                    ? `Showing ${filteredKeys.length} of ${totalCount} total keys`
                    : loading
                      ? "Loading keys..."
                      : `${filteredKeys.length} keys`}
                </p>
              </div>
            </div>
          </div>
        </div>

        <div class="p-4">
          <AdminApiKeyTable
            keys={filteredKeys}
            {loading}
            onChanged={() => loadKeys({ reset: true })}
            onSecret={handleSecret}
          />

          {#if nextCursor}
            <div class="mt-4 flex justify-center">
              <Button variant="outlined" on:click={() => loadKeys({ reset: false })} class="gap-2">
                {#if loadingMore}
                  <div class="h-4 w-4 animate-spin rounded-full border-2 border-current border-t-transparent"></div>
                  Loading...
                {:else}
                  Load more
                {/if}
              </Button>
            </div>
          {/if}
        </div>
      </div>

      <!-- Policy Section -->
      <div class="rounded-xl border border-default bg-primary shadow-sm overflow-hidden">
        <div class="px-6 py-4 border-b border-default bg-subtle/30">
          <div class="flex items-center gap-3">
            <div class="flex h-10 w-10 items-center justify-center rounded-xl bg-purple-100 dark:bg-purple-900/30">
              <Shield class="h-5 w-5 text-purple-600 dark:text-purple-400" />
            </div>
            <div>
              <h3 class="font-semibold text-default">Tenant Policy</h3>
              <p class="text-xs text-muted">Configure API key policies and restrictions</p>
            </div>
          </div>
        </div>
        <div class="p-6">
          <ApiKeyPolicyPanel />
        </div>
      </div>

      <!-- Super Key Status Section -->
      <div class="rounded-xl border border-default bg-primary shadow-sm overflow-hidden">
        <div class="px-6 py-4 border-b border-default bg-subtle/30">
          <div class="flex items-center gap-3">
            <div class="flex h-10 w-10 items-center justify-center rounded-xl bg-orange-100 dark:bg-orange-900/30">
              <Building2 class="h-5 w-5 text-orange-600 dark:text-orange-400" />
            </div>
            <div>
              <h3 class="font-semibold text-default">Super Key Status</h3>
              <p class="text-xs text-muted">Tenant-wide API key administration</p>
            </div>
          </div>
        </div>
        <div class="p-6">
          <SuperKeyStatusPanel />
        </div>
      </div>
    </div>
  </Page.Main>
</Page.Root>

<Dialog.Root bind:isOpen={secretDialogOpen} alert>
  <Dialog.Content width="medium">
    <Dialog.Title class="flex items-center gap-3">
      <div class="flex h-10 w-10 items-center justify-center rounded-xl bg-green-100 dark:bg-green-900/30">
        <Key class="h-5 w-5 text-green-600 dark:text-green-400" />
      </div>
      <span>{m.api_key()}</span>
    </Dialog.Title>
    <Dialog.Description>
      <div class="mt-2 flex items-start gap-2 text-yellow-700 dark:text-yellow-300">
        <AlertCircle class="h-4 w-4 flex-shrink-0 mt-0.5" />
        <span>{@html m.generate_api_key_warning()}</span>
      </div>
    </Dialog.Description>
    {#if latestSecret}
      <div class="mt-5">
        <CodeBlock code={latestSecret} />
        <div class="mt-4 flex items-center gap-3">
          <Button
            variant="primary"
            on:click={() => {
              navigator.clipboard.writeText(latestSecret ?? "");
            }}
            class="gap-2"
          >
            Copy key
          </Button>
        </div>
      </div>
    {/if}
    <Dialog.Controls let:close>
      <Button is={close} variant="outlined">{m.close()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
