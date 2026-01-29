<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Dialog } from "@intric/ui";
  import { createEventDispatcher } from "svelte";
  import { writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import type { ModelProviderPublic } from "@intric/intric-js";
  import ProviderGlyph from "../components/ProviderGlyph.svelte";
  import ProviderStatusBadge from "../components/ProviderStatusBadge.svelte";
  import { ChevronRight, Search, LayoutGrid } from "lucide-svelte";
  import { getIntric } from "$lib/core/Intric";

  export let providers: ModelProviderPublic[] = [];
  export let selectedProviderId: string | null = null;

  const dispatch = createEventDispatcher<{
    select: { providerId: string | null; isNew: boolean; providerType: string };
  }>();

  const intric = getIntric();

  // Provider types available for creation
  // Note: type values must be LiteLLM-compatible provider types
  const providerTypes = [
    { type: "openai", label: "OpenAI", description: "OpenAI and compatible cloud APIs (Together, Groq, Fireworks)" },
    { type: "azure", label: "Azure OpenAI", description: "Enterprise Azure deployments" },
    { type: "anthropic", label: "Anthropic", description: "Claude 4, Claude 3.5" },
    { type: "gemini", label: "Google Gemini", description: "Gemini Pro, Gemini Flash" },
    { type: "cohere", label: "Cohere", description: "Command, Embed models" },
    { type: "mistral", label: "Mistral AI", description: "Mistral, Mixtral models" },
    { type: "hosted_vllm", label: "vLLM", description: "Self-hosted vLLM inference server" }
  ] as const;

  const featuredTypes = new Set(providerTypes.map((p) => p.type));

  type ViewMode = "select" | "create";
  let viewMode: ViewMode = providers.length > 0 ? "select" : "create";

  // Selection state
  let hoveredProvider: string | null = null;
  let selectedNewProviderType: string | null = null;

  const providerOrigins: Record<string, string> = {
    openai: "🇺🇸 USA",
    azure: "🇺🇸 USA",
    anthropic: "🇺🇸 USA",
    gemini: "🇺🇸 USA",
    cohere: "🇨🇦 Canada",
    mistral: "🇫🇷 France",
    hosted_vllm: "",
    deepseek: "🇨🇳 China",
    ai21: "🇮🇱 Israel",
    aleph_alpha: "🇩🇪 Germany",
    amazon: "🇺🇸 USA",
    bedrock: "🇺🇸 USA",
    cerebras: "🇺🇸 USA",
    cloudflare: "🇺🇸 USA",
    databricks: "🇺🇸 USA",
    fireworks_ai: "🇺🇸 USA",
    friendliai: "🇰🇷 South Korea",
    groq: "🇺🇸 USA",
    huggingface: "🇺🇸 USA",
    nscale: "🇬🇧 UK",
    nvidia_nim: "🇺🇸 USA",
    ollama: "",
    perplexity: "🇺🇸 USA",
    replicate: "🇺🇸 USA",
    sambanova: "🇺🇸 USA",
    together_ai: "🇺🇸 USA",
    vertex_ai: "🇺🇸 USA",
    voyage: "🇺🇸 USA",
    xai: "🇺🇸 USA",
    zhipuai: "🇨🇳 China",
    moonshot: "🇨🇳 China",
    baidu: "🇨🇳 China",
    volcengine: "🇨🇳 China",
  };

  // Browse all providers dialog
  const browseDialogOpen = writable(false);
  let allProviders: { type: string; label: string; origin: string }[] = [];
  let searchQuery = "";
  let loadingCapabilities = false;
  let capabilitiesLoaded = false;

  $: filteredProviders = searchQuery
    ? allProviders.filter((p) => p.label.toLowerCase().includes(searchQuery.toLowerCase()))
    : allProviders;

  async function openBrowseDialog() {
    browseDialogOpen.set(true);
    if (!capabilitiesLoaded) {
      loadingCapabilities = true;
      try {
        const capabilities = await intric.modelProviders.getCapabilities();
        allProviders = Object.entries(capabilities)
          .filter(([type]) => !featuredTypes.has(type))
          .map(([type]) => ({
            type,
            label: formatProviderName(type),
            origin: providerOrigins[type] ?? ""
          }))
          .sort((a, b) => a.label.localeCompare(b.label));
        capabilitiesLoaded = true;
      } catch {
        // Silently fail
      } finally {
        loadingCapabilities = false;
      }
    }
  }

  function selectFromBrowse(type: string) {
    browseDialogOpen.set(false);
    searchQuery = "";
    selectNewProviderType(type);
  }

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
</script>

<div class="flex flex-col gap-6">
  {#if providers.length > 0}
    <!-- View Mode Toggle - Refined underline tabs -->
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
              <span class="text-sm text-muted">{provider.provider_type}</span>
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
    <div class="flex flex-col gap-3">
      <h3 class="text-sm font-medium text-muted">{m.select_provider_type()}</h3>

      <div class="grid grid-cols-1 sm:grid-cols-2 gap-3">
        {#each providerTypes as { type, label, description }}
          {@const isSelected = selectedNewProviderType === type}
          <button
            type="button"
            class="group flex items-start gap-3 rounded-lg border p-4 text-left transition-all duration-150
              focus-visible:outline-none focus-visible:border-accent-default focus-visible:ring-1 focus-visible:ring-accent-default/80 focus-visible:ring-offset-0
              {isSelected
                ? 'border-accent-default bg-accent-dimmer ring-1 ring-accent-default'
                : 'border-dimmer hover:border-accent-default/40 hover:bg-hover-dimmer'}"
            on:click={() => selectNewProviderType(type)}
          >
            <div class="transition-transform duration-150 group-hover:scale-105">
              <ProviderGlyph {type} size="md" />
            </div>

            <div class="flex-1 min-w-0">
              <div class="flex items-center gap-2">
                <span class="font-medium text-primary">{label}</span>
                {#if providerOrigins[type]}
                  <span class="inline-flex items-center rounded-full bg-surface-dimmer px-2 py-0.5 text-xs text-muted">{providerOrigins[type]}</span>
                {/if}
              </div>
              <p class="text-sm text-muted mt-0.5">{description}</p>
            </div>

            <div class="flex h-5 w-5 items-center justify-center rounded-full border transition-all duration-150
              {isSelected
                ? 'border-accent-default bg-accent-default'
                : 'border-dimmer group-hover:border-accent-default/60'}">
              {#if isSelected}
                <div class="h-2 w-2 rounded-full bg-white"></div>
              {/if}
            </div>
          </button>
        {/each}
        <!-- Browse all providers card -->
        <button
          type="button"
          class="group flex items-start gap-3 rounded-lg border border-dashed p-4 text-left transition-all duration-150
            focus-visible:outline-none focus-visible:border-accent-default focus-visible:ring-1 focus-visible:ring-accent-default/80 focus-visible:ring-offset-0
            border-dimmer hover:border-accent-default/40 hover:bg-hover-dimmer"
          on:click={openBrowseDialog}
        >
          <div class="flex h-10 w-10 items-center justify-center rounded-lg bg-surface-dimmer text-muted transition-transform duration-150 group-hover:scale-105">
            <LayoutGrid class="h-5 w-5" />
          </div>

          <div class="flex-1 min-w-0">
            <span class="font-medium text-primary">{m.more_providers()}</span>
            <p class="text-sm text-muted mt-0.5">{m.browse_all_providers_description()}</p>
          </div>
        </button>
      </div>
    </div>
  {/if}
</div>

<!-- Browse All Providers Dialog -->
<Dialog.Root openController={browseDialogOpen}>
  <Dialog.Content width="large" form>
    <Dialog.Title>
      {m.more_providers()}
    </Dialog.Title>

    <Dialog.Section class="flex flex-col gap-4">
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
      {:else if filteredProviders.length === 0}
        <p class="text-sm text-muted text-center py-8">{m.no_providers_found()}</p>
      {:else}
        <div class="grid grid-cols-1 sm:grid-cols-2 gap-2 max-h-80 overflow-y-auto">
          {#each filteredProviders as { type, label, origin }}
            <button
              type="button"
              class="group flex items-center gap-3 rounded-lg border p-3 text-left transition-all duration-150
                focus-visible:outline-none focus-visible:border-accent-default focus-visible:ring-1 focus-visible:ring-accent-default/80
                border-dimmer hover:border-accent-default/40 hover:bg-hover-dimmer"
              on:click={() => selectFromBrowse(type)}
            >
              <div class="transition-transform duration-150 group-hover:scale-105">
                <ProviderGlyph {type} size="md" />
              </div>

              <div class="flex-1 min-w-0">
                <div class="flex items-center gap-2">
                  <span class="font-medium text-primary text-sm">{label}</span>
                  {#if origin}
                    <span class="inline-flex items-center rounded-full bg-surface-dimmer px-1.5 py-0.5 text-xs text-muted leading-none">{origin}</span>
                  {/if}
                </div>
                <p class="text-xs text-muted font-mono">{type}</p>
              </div>

              <ChevronRight class="h-4 w-4 text-muted group-hover:text-primary transition-colors" />
            </button>
          {/each}
        </div>
      {/if}
    </Dialog.Section>
  </Dialog.Content>
</Dialog.Root>
