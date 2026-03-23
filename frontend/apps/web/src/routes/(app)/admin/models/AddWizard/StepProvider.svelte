<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { createEventDispatcher } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import type { ModelProviderPublic } from "@intric/intric-js";
  import ProviderGlyph from "../components/ProviderGlyph.svelte";
  import ProviderStatusBadge from "../components/ProviderStatusBadge.svelte";
  import { ChevronRight, Search, Star } from "lucide-svelte";
  import { getIntric } from "$lib/core/Intric";

  export let providers: ModelProviderPublic[] = [];
  export let favoriteProviders: string[] = [];
  export let selectedProviderId: string | null = null;
  /** Capabilities loaded by parent (AddWizard) */
  export let capabilities: { providers: Record<string, any>; default_fields: any[] } | null = null;

  const dispatch = createEventDispatcher<{
    select: { providerId: string | null; isNew: boolean; providerType: string };
  }>();

  const intric = getIntric();

  type ViewMode = "select" | "create";
  let viewMode: ViewMode = providers.length > 0 ? "select" : "create";

  // Selection state
  let hoveredProvider: string | null = null;
  let selectedNewProviderType: string | null = null;

  // All providers derived from capabilities prop
  $: allCapabilityProviders = capabilities
    ? Object.keys(capabilities.providers)
        .map((type) => ({ type, label: formatProviderName(type) }))
        .sort((a, b) => a.label.localeCompare(b.label))
    : [];

  $: loadingCapabilities = !capabilities;

  // Search
  let searchQuery = "";

  // Local copy of favorites for optimistic updates
  let localFavorites: string[] = [...favoriteProviders];

  $: favoritesSet = new Set(localFavorites);

  // Compute favorite provider cards from capabilities data (or fallback labels)
  $: favoriteCards = localFavorites
    .map((type) => {
      const found = allCapabilityProviders.find((p) => p.type === type);
      return { type, label: found?.label || formatProviderName(type) };
    });

  // Search filter — searchQuery must be referenced directly in the $: statement
  // so Svelte 4 tracks it as a reactive dependency.
  $: filteredFavorites = favoriteCards
    .filter((p) => {
      if (!searchQuery) return true;
      const q = searchQuery.toLowerCase();
      return p.label.toLowerCase().includes(q) || p.type.toLowerCase().includes(q);
    });

  $: otherProviders = allCapabilityProviders
    .filter((p) => !favoritesSet.has(p.type))
    .filter((p) => {
      if (!searchQuery) return true;
      const q = searchQuery.toLowerCase();
      return p.label.toLowerCase().includes(q) || p.type.toLowerCase().includes(q);
    });

  function formatProviderName(type: string): string {
    return type
      .replace(/_/g, " ")
      .replace(/\b\w/g, (c) => c.toUpperCase());
  }

  function selectExistingProvider(provider: ModelProviderPublic) {
    dispatch("select", {
      providerId: provider.id,
      isNew: false,
      providerType: provider.provider_type
    });
  }

  function selectNewProviderType(type: string) {
    selectedNewProviderType = type;
    dispatch("select", {
      providerId: null,
      isNew: true,
      providerType: type
    });
  }

  async function toggleFavorite(type: string, event: MouseEvent) {
    event.stopPropagation();
    let updated: string[];
    if (favoritesSet.has(type)) {
      updated = localFavorites.filter((t) => t !== type);
    } else {
      updated = [...localFavorites, type];
    }
    localFavorites = updated;
    // Persist to backend (fire and forget)
    try {
      await intric.modelProviders.setFavorites(updated);
    } catch {
      // Revert on failure
      localFavorites = [...favoriteProviders];
    }
  }
</script>

<div class="flex flex-col gap-6">
  {#if providers.length > 0}
    <!-- View Mode Toggle -->
    <div class="flex border-b border-dimmer">
      <button
        type="button"
        class="relative px-4 py-2.5 text-sm font-medium transition-all duration-150
          focus-visible:outline-none focus-visible:text-primary
          {viewMode === 'select'
            ? 'text-primary'
            : 'text-muted hover:text-primary'}"
        on:click={() => viewMode = "select"}
      >
        {m.use_existing_provider()}
        {#if viewMode === "select"}
          <span class="absolute bottom-0 left-2 right-2 h-0.5 bg-accent-default rounded-full"></span>
        {/if}
      </button>
      <button
        type="button"
        class="relative px-4 py-2.5 text-sm font-medium transition-all duration-150
          focus-visible:outline-none focus-visible:text-primary
          {viewMode === 'create'
            ? 'text-primary'
            : 'text-muted hover:text-primary'}"
        on:click={() => viewMode = "create"}
      >
        {m.create_new_provider()}
        {#if viewMode === "create"}
          <span class="absolute bottom-0 left-2 right-2 h-0.5 bg-accent-default rounded-full"></span>
        {/if}
      </button>
    </div>
  {/if}

  {#if viewMode === "select" && providers.length > 0}
    <!-- Existing Providers List -->
    <div class="flex flex-col gap-4">
      <h3 class="text-sm font-medium text-muted">{m.select_provider()}</h3>

      <div class="flex flex-col gap-3">
        {#each providers as provider}
          {@const isSelected = provider.id === selectedProviderId}
          <button
            type="button"
            class="group flex items-center gap-4 rounded-lg border p-4 text-left transition-all duration-150
              border-dimmer hover:border-stronger hover:bg-hover-dimmer active:bg-accent-dimmer
              focus-visible:outline-none focus-visible:border-accent-default focus-visible:ring-1 focus-visible:ring-accent-default/80 focus-visible:ring-offset-0"
            on:click={() => selectExistingProvider(provider)}
            on:mouseenter={() => hoveredProvider = provider.id}
            on:mouseleave={() => hoveredProvider = null}
          >
            <div class="transition-transform duration-150 group-hover:scale-105">
              <ProviderGlyph type={provider.provider_type} size="md" />
            </div>

            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="font-medium text-primary truncate">{provider.name}</span>
                <ProviderStatusBadge {provider} />
              </div>
            </div>

            <ChevronRight
              class="h-5 w-5 text-muted transition-all duration-150
                {isSelected ? 'text-accent-default translate-x-0.5' : 'group-hover:text-primary group-hover:translate-x-1'}"
            />
          </button>
        {/each}
      </div>
    </div>
  {:else}
    <!-- Create New Provider -->
    <div class="flex flex-col gap-5">
      <!-- Search -->
      <div class="relative">
        <Search class="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted" />
        <input
          type="text"
          bind:value={searchQuery}
          placeholder={m.search_providers()}
          class="w-full rounded-lg border border-dimmer bg-surface pl-9 pr-3 py-2 text-sm
            placeholder:text-muted focus:outline-none focus:border-accent-default focus:ring-1 focus:ring-accent-default/80"
        />
      </div>

      {#if loadingCapabilities}
        <div class="flex items-center justify-center py-12">
          <div class="h-6 w-6 animate-spin rounded-full border-2 border-accent-default border-t-transparent"></div>
        </div>
      {:else}
        <!-- Favorites Section -->
        {#if filteredFavorites.length > 0}
          <div class="flex flex-col gap-3">
            <h3 class="text-sm font-medium text-muted">{m.favorite_providers()}</h3>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2">
              {#each filteredFavorites as { type, label }}
                {@const isSelected = selectedNewProviderType === type}
                <!-- svelte-ignore a11y-no-static-element-interactions -->
                <div
                  class="group flex items-center gap-3 rounded-lg border p-3 text-left transition-all duration-150 cursor-pointer
                    focus-within:border-accent-default focus-within:ring-1 focus-within:ring-accent-default/80
                    {isSelected
                      ? 'border-accent-default bg-accent-dimmer ring-1 ring-accent-default'
                      : 'border-dimmer hover:border-accent-default/40 hover:bg-hover-dimmer'}"
                  on:click={() => selectNewProviderType(type)}
                  on:keydown={(e) => e.key === 'Enter' && selectNewProviderType(type)}
                >
                  <div class="transition-transform duration-150 group-hover:scale-105">
                    <ProviderGlyph {type} size="md" />
                  </div>

                  <div class="flex-1 min-w-0">
                    <span class="font-medium text-primary text-sm">{label}</span>
                  </div>

                  <button
                    type="button"
                    class="p-1 rounded transition-colors hover:bg-surface-dimmer focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-default"
                    on:click|stopPropagation={(e) => toggleFavorite(type, e)}
                    title={m.unpin_provider()}
                  >
                    <Star class="h-4 w-4 fill-warning-default text-warning-default" />
                  </button>
                </div>
              {/each}
            </div>
          </div>
        {/if}

        <!-- All Providers Section -->
        {#if otherProviders.length > 0}
          <div class="flex flex-col gap-3">
            <h3 class="text-sm font-medium text-muted">{m.all_providers()}</h3>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-64 overflow-y-auto">
              {#each otherProviders as { type, label }}
                {@const isSelected = selectedNewProviderType === type}
                <!-- svelte-ignore a11y-no-static-element-interactions -->
                <div
                  class="group flex items-center gap-3 rounded-lg border p-3 text-left transition-all duration-150 cursor-pointer
                    focus-within:border-accent-default focus-within:ring-1 focus-within:ring-accent-default/80
                    {isSelected
                      ? 'border-accent-default bg-accent-dimmer ring-1 ring-accent-default'
                      : 'border-dimmer hover:border-accent-default/40 hover:bg-hover-dimmer'}"
                  on:click={() => selectNewProviderType(type)}
                  on:keydown={(e) => e.key === 'Enter' && selectNewProviderType(type)}
                >
                  <div class="transition-transform duration-150 group-hover:scale-105">
                    <ProviderGlyph {type} size="md" />
                  </div>

                  <div class="flex-1 min-w-0">
                    <span class="font-medium text-primary text-sm">{label}</span>
                  </div>

                  <button
                    type="button"
                    class="p-1 rounded transition-colors hover:bg-surface-dimmer opacity-0 group-hover:opacity-100 focus-visible:opacity-100 focus-visible:outline-none focus-visible:ring-1 focus-visible:ring-accent-default"
                    on:click|stopPropagation={(e) => toggleFavorite(type, e)}
                    title={m.pin_provider()}
                  >
                    <Star class="h-4 w-4 text-muted" />
                  </button>
                </div>
              {/each}
            </div>
          </div>
        {:else if searchQuery && filteredFavorites.length === 0}
          <p class="text-sm text-muted text-center py-8">{m.no_providers_found()}</p>
        {/if}
      {/if}
    </div>
  {/if}
</div>
