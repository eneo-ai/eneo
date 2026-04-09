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
  export let capabilities: {
    providers: Record<string, unknown>;
    default_fields: unknown[];
  } | null = null;

  const dispatch = createEventDispatcher<{
    select: { providerId: string | null; isNew: boolean; providerType: string };
  }>();

  const intric = getIntric();

  type ViewMode = "select" | "create";
  let viewMode: ViewMode = providers.length > 0 ? "select" : "create";

  // Selection state
  let _hoveredProvider: string | null = null;
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
  $: favoriteCards = localFavorites.map((type) => {
    const found = allCapabilityProviders.find((p) => p.type === type);
    return { type, label: found?.label || formatProviderName(type) };
  });

  // Search filter — searchQuery must be referenced directly in the $: statement
  // so Svelte 4 tracks it as a reactive dependency.
  $: filteredFavorites = favoriteCards.filter((p) => {
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
    return type.replace(/_/g, " ").replace(/\b\w/g, (c) => c.toUpperCase());
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
    <div class="border-dimmer flex border-b">
      <button
        type="button"
        class="focus-visible:text-primary relative px-4 py-2.5 text-sm font-medium transition-all
          duration-150 focus-visible:outline-none
          {viewMode === 'select' ? 'text-primary' : 'text-muted hover:text-primary'}"
        on:click={() => (viewMode = "select")}
      >
        {m.use_existing_provider()}
        {#if viewMode === "select"}
          <span class="bg-accent-default absolute right-2 bottom-0 left-2 h-0.5 rounded-full"
          ></span>
        {/if}
      </button>
      <button
        type="button"
        class="focus-visible:text-primary relative px-4 py-2.5 text-sm font-medium transition-all
          duration-150 focus-visible:outline-none
          {viewMode === 'create' ? 'text-primary' : 'text-muted hover:text-primary'}"
        on:click={() => (viewMode = "create")}
      >
        {m.create_new_provider()}
        {#if viewMode === "create"}
          <span class="bg-accent-default absolute right-2 bottom-0 left-2 h-0.5 rounded-full"
          ></span>
        {/if}
      </button>
    </div>
  {/if}

  {#if viewMode === "select" && providers.length > 0}
    <!-- Existing Providers List -->
    <div class="flex flex-col gap-4">
      <h3 class="text-muted text-sm font-medium">{m.select_provider()}</h3>

      <div class="flex flex-col gap-3">
        {#each providers as provider (provider.id)}
          {@const isSelected = provider.id === selectedProviderId}
          <button
            type="button"
            class="group border-dimmer hover:border-stronger hover:bg-hover-dimmer active:bg-accent-dimmer focus-visible:border-accent-default focus-visible:ring-accent-default/80 flex items-center gap-4
              rounded-lg border p-4 text-left
              transition-all duration-150 focus-visible:ring-1 focus-visible:ring-offset-0 focus-visible:outline-none"
            on:click={() => selectExistingProvider(provider)}
            on:mouseenter={() => (_hoveredProvider = provider.id)}
            on:mouseleave={() => (_hoveredProvider = null)}
          >
            <div class="transition-transform duration-150 group-hover:scale-105">
              <ProviderGlyph type={provider.provider_type} size="md" />
            </div>

            <div class="min-w-0 flex-1">
              <div class="flex items-center gap-2">
                <span class="text-primary truncate font-medium">{provider.name}</span>
                <ProviderStatusBadge {provider} />
              </div>
            </div>

            <ChevronRight
              class="text-muted h-5 w-5 transition-all duration-150
                {isSelected
                ? 'text-accent-default translate-x-0.5'
                : 'group-hover:text-primary group-hover:translate-x-1'}"
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
        <Search class="text-muted absolute top-1/2 left-3 h-4 w-4 -translate-y-1/2" />
        <input
          type="text"
          bind:value={searchQuery}
          placeholder={m.search_providers()}
          class="border-dimmer bg-surface placeholder:text-muted focus:border-accent-default focus:ring-accent-default/80 w-full rounded-lg border py-2
            pr-3 pl-9 text-sm focus:ring-1 focus:outline-none"
        />
      </div>

      {#if loadingCapabilities}
        <div class="flex items-center justify-center py-12">
          <div
            class="border-accent-default h-6 w-6 animate-spin rounded-full border-2 border-t-transparent"
          ></div>
        </div>
      {:else}
        <!-- Favorites Section -->
        {#if filteredFavorites.length > 0}
          <div class="flex flex-col gap-3">
            <h3 class="text-muted text-sm font-medium">{m.favorite_providers()}</h3>
            <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
              {#each filteredFavorites as { type, label } (type)}
                {@const isSelected = selectedNewProviderType === type}
                <!-- svelte-ignore a11y-no-static-element-interactions -->
                <div
                  class="group focus-within:border-accent-default focus-within:ring-accent-default/80 flex cursor-pointer items-center gap-3 rounded-lg border p-3 text-left
                    transition-all duration-150 focus-within:ring-1
                    {isSelected
                    ? 'border-accent-default bg-accent-dimmer ring-accent-default ring-1'
                    : 'border-dimmer hover:border-accent-default/40 hover:bg-hover-dimmer'}"
                  on:click={() => selectNewProviderType(type)}
                  on:keydown={(e) => e.key === "Enter" && selectNewProviderType(type)}
                >
                  <div class="transition-transform duration-150 group-hover:scale-105">
                    <ProviderGlyph {type} size="md" />
                  </div>

                  <div class="min-w-0 flex-1">
                    <span class="text-primary text-sm font-medium">{label}</span>
                  </div>

                  <button
                    type="button"
                    class="hover:bg-surface-dimmer focus-visible:ring-accent-default rounded p-1 transition-colors focus-visible:ring-1 focus-visible:outline-none"
                    on:click|stopPropagation={(e) => toggleFavorite(type, e)}
                    title={m.unpin_provider()}
                  >
                    <Star class="fill-warning-default text-warning-default h-4 w-4" />
                  </button>
                </div>
              {/each}
            </div>
          </div>
        {/if}

        <!-- All Providers Section -->
        {#if otherProviders.length > 0}
          <div class="flex flex-col gap-3">
            <h3 class="text-muted text-sm font-medium">{m.all_providers()}</h3>
            <div class="grid max-h-64 grid-cols-1 gap-2 overflow-y-auto sm:grid-cols-2">
              {#each otherProviders as { type, label } (type)}
                {@const isSelected = selectedNewProviderType === type}
                <!-- svelte-ignore a11y-no-static-element-interactions -->
                <div
                  class="group focus-within:border-accent-default focus-within:ring-accent-default/80 flex cursor-pointer items-center gap-3 rounded-lg border p-3 text-left
                    transition-all duration-150 focus-within:ring-1
                    {isSelected
                    ? 'border-accent-default bg-accent-dimmer ring-accent-default ring-1'
                    : 'border-dimmer hover:border-accent-default/40 hover:bg-hover-dimmer'}"
                  on:click={() => selectNewProviderType(type)}
                  on:keydown={(e) => e.key === "Enter" && selectNewProviderType(type)}
                >
                  <div class="transition-transform duration-150 group-hover:scale-105">
                    <ProviderGlyph {type} size="md" />
                  </div>

                  <div class="min-w-0 flex-1">
                    <span class="text-primary text-sm font-medium">{label}</span>
                  </div>

                  <button
                    type="button"
                    class="hover:bg-surface-dimmer focus-visible:ring-accent-default rounded p-1 opacity-0 transition-colors group-hover:opacity-100 focus-visible:opacity-100 focus-visible:ring-1 focus-visible:outline-none"
                    on:click|stopPropagation={(e) => toggleFavorite(type, e)}
                    title={m.pin_provider()}
                  >
                    <Star class="text-muted h-4 w-4" />
                  </button>
                </div>
              {/each}
            </div>
          </div>
        {:else if searchQuery && filteredFavorites.length === 0}
          <p class="text-muted py-8 text-center text-sm">{m.no_providers_found()}</p>
        {/if}
      {/if}
    </div>
  {/if}
</div>
