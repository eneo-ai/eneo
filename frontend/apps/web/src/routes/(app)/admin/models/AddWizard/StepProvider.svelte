<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Step 1 — pick a provider.

  Two surfaces:
    - "Use existing"  — shown when the tenant already has providers configured.
    - "Create new"    — pick a provider type from a searchable, favouritable
                        grid populated from `capabilities.providers`.

  The two surfaces are presented as shadcn Tabs (the host page may pre-pick
  one when there are no existing providers yet, which suppresses the toggle).

  Selection is reported via `onSelect(detail)`. The parent wizard decides
  what the next step is — picking an existing provider skips Credentials.
-->

<script lang="ts">
  import { untrack } from "svelte";
  import { Search, Star } from "lucide-svelte";
  import type { ModelProviderPublic } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";
  import { getIntric } from "$lib/core/Intric";

  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

  import ProviderGlyph from "../components/ProviderGlyph.svelte";
  import {
    formatProviderLabel,
    listProviderOptions,
    type ModelProviderCapabilities
  } from "../modelProviderCapabilities";

  let {
    providers = [],
    favoriteProviders = [],
    selectedProviderId = null,
    capabilities = null,
    onSelect
  }: {
    providers?: ModelProviderPublic[];
    favoriteProviders?: string[];
    selectedProviderId?: string | null;
    capabilities?: ModelProviderCapabilities | null;
    onSelect: (detail: { providerId: string | null; isNew: boolean; providerType: string }) => void;
  } = $props();

  const intric = getIntric();

  // --- Tabs --------------------------------------------------------------

  // Two distinct flows: pick existing vs create new. The tab is auto-set
  // to "create" when the tenant has no providers yet, then hidden. We seed
  // both pieces of state once from the props — providers/favouriteProviders
  // can change while the wizard is open (e.g. after creating a provider in
  // step 2), but those changes shouldn't reset what the user is viewing.
  let viewMode = $state<"select" | "create">(
    untrack(() => (providers.length > 0 ? "select" : "create"))
  );

  // --- Search & favourites ----------------------------------------------

  let searchQuery = $state("");
  let localFavorites = $state<string[]>(untrack(() => [...favoriteProviders]));

  const favoritesSet = $derived(new Set(localFavorites));

  const allCapabilityProviders = $derived(listProviderOptions(capabilities));
  const loadingCapabilities = $derived(!capabilities);

  const favoriteCards = $derived(
    localFavorites.map((value) => {
      const found = allCapabilityProviders.find((p) => p.value === value);
      return { value, label: found?.label ?? formatProviderLabel(value) };
    })
  );

  function matches(label: string, type: string, q: string) {
    if (!q) return true;
    const needle = q.toLowerCase();
    return label.toLowerCase().includes(needle) || type.toLowerCase().includes(needle);
  }

  const filteredFavorites = $derived(
    favoriteCards.filter((p) => matches(p.label, p.value, searchQuery))
  );

  const otherProviders = $derived(
    allCapabilityProviders
      .filter((p) => !favoritesSet.has(p.value))
      .filter((p) => matches(p.label, p.value, searchQuery))
  );

  // --- Selection state for "create new" ---------------------------------

  let selectedNewProviderType = $state<string | null>(null);

  function selectExistingProvider(provider: ModelProviderPublic) {
    onSelect({ providerId: provider.id, isNew: false, providerType: provider.provider_type });
  }

  function selectNewProviderType(type: string) {
    selectedNewProviderType = type;
    onSelect({ providerId: null, isNew: true, providerType: type });
  }

  async function toggleFavorite(type: string) {
    const next = favoritesSet.has(type)
      ? localFavorites.filter((t) => t !== type)
      : [...localFavorites, type];
    const previous = localFavorites;
    localFavorites = next;
    try {
      await intric.modelProviders.setFavorites(next);
    } catch {
      localFavorites = previous;
    }
  }
</script>

<div class="flex flex-col gap-6">
  {#if providers.length > 0}
    <Tabs.Root bind:value={viewMode}>
      <Tabs.List variant="line" class="w-full justify-start">
        <Tabs.Trigger value="select">{m.use_existing_provider()}</Tabs.Trigger>
        <Tabs.Trigger value="create">{m.create_new_provider()}</Tabs.Trigger>
      </Tabs.List>

      <Tabs.Content value="select" class="mt-4 flex flex-col gap-4">
        <h3 class="text-muted-foreground text-sm font-medium">{m.select_provider()}</h3>
        <ul class="flex flex-col gap-3">
          {#each providers as provider (provider.id)}
            {@const isSelected = provider.id === selectedProviderId}
            <li>
              <button
                type="button"
                data-selected={isSelected ? "" : undefined}
                class="
                  group border-border hover:bg-muted/50
                  focus-visible:border-ring focus-visible:ring-ring/50
                  data-[selected]:border-accent-default data-[selected]:bg-accent-dimmer/30 flex w-full items-center gap-4 rounded-lg border
                  p-4 text-left
                  transition-colors duration-150
                  focus-visible:ring-3 focus-visible:outline-none
                "
                onclick={() => selectExistingProvider(provider)}
              >
                <ProviderGlyph providerType={provider.provider_type} size="md" />
                <div class="min-w-0 flex-1">
                  <div class="flex items-center gap-2">
                    <span class="text-foreground truncate font-medium">{provider.name}</span>
                  </div>
                </div>
              </button>
            </li>
          {/each}
        </ul>
      </Tabs.Content>

      <Tabs.Content value="create" class="mt-4">
        {@render createPanel()}
      </Tabs.Content>
    </Tabs.Root>
  {:else}
    {@render createPanel()}
  {/if}
</div>

{#snippet createPanel()}
  <div class="flex flex-col gap-5">
    <div class="relative">
      <Search
        class="text-muted-foreground absolute top-1/2 left-3 size-4 -translate-y-1/2"
        aria-hidden="true"
      />
      <Input
        type="text"
        bind:value={searchQuery}
        placeholder={m.search_providers()}
        class="pl-9"
        aria-label={m.search_providers()}
      />
    </div>

    {#if loadingCapabilities}
      <div class="flex items-center justify-center py-12">
        <div
          class="border-accent-default size-6 animate-spin rounded-full border-2 border-t-transparent"
          role="status"
          aria-label={m.loading()}
        ></div>
      </div>
    {:else}
      {#if filteredFavorites.length > 0}
        <section class="flex flex-col gap-3" aria-label={m.favorite_providers()}>
          <h3 class="text-muted-foreground text-sm font-medium">{m.favorite_providers()}</h3>
          <div class="grid grid-cols-1 gap-2 sm:grid-cols-2">
            {#each filteredFavorites as provider (provider.value)}
              {@render providerCard(provider, true)}
            {/each}
          </div>
        </section>
      {/if}

      {#if otherProviders.length > 0}
        <section class="flex flex-col gap-3" aria-label={m.all_providers()}>
          <h3 class="text-muted-foreground text-sm font-medium">{m.all_providers()}</h3>
          <div class="grid max-h-64 grid-cols-1 gap-2 overflow-y-auto sm:grid-cols-2">
            {#each otherProviders as provider (provider.value)}
              {@render providerCard(provider, false)}
            {/each}
          </div>
        </section>
      {:else if searchQuery && filteredFavorites.length === 0}
        <p class="text-muted-foreground py-8 text-center text-sm">{m.no_providers_found()}</p>
      {/if}
    {/if}
  </div>
{/snippet}

{#snippet providerCard(provider: { value: string; label: string }, isFavorite: boolean)}
  {@const isSelected = selectedNewProviderType === provider.value}
  <div
    class="
      group has-[:focus-visible]:border-ring has-[:focus-visible]:ring-ring/50 relative flex items-center gap-3 rounded-lg
      border p-3
      transition-colors duration-150 has-[:focus-visible]:ring-3
      {isSelected
      ? 'border-accent-default bg-accent-dimmer ring-accent-default ring-1'
      : 'border-border hover:border-accent-default/40 hover:bg-muted/40'}
    "
  >
    <!-- Card-level click target. We use a real <button> with an absolute
         expanding hit area; the favourite toggle floats above it as its own
         interactive element to avoid nested clickables. -->
    <button
      type="button"
      onclick={() => selectNewProviderType(provider.value)}
      class="absolute inset-0 rounded-lg outline-none"
      aria-label={provider.label}
    ></button>

    <ProviderGlyph providerType={provider.value} size="md" />
    <div class="pointer-events-none min-w-0 flex-1">
      <span class="text-foreground text-sm font-medium">{provider.label}</span>
    </div>
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      class="
        relative z-10 shrink-0
        {isFavorite
        ? ''
        : 'opacity-0 transition-opacity group-hover:opacity-100 focus-visible:opacity-100'}
      "
      onclick={() => void toggleFavorite(provider.value)}
      aria-label={isFavorite ? m.unpin_provider() : m.pin_provider()}
      title={isFavorite ? m.unpin_provider() : m.pin_provider()}
    >
      <Star
        class={isFavorite ? "fill-warning-default text-warning-default" : "text-muted-foreground"}
      />
    </Button>
  </div>
{/snippet}
