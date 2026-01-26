<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Button } from "@intric/ui";
  import { createEventDispatcher } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import type { ModelProviderPublic } from "@intric/intric-js";
  import ProviderGlyph from "../components/ProviderGlyph.svelte";
  import ProviderStatusBadge from "../components/ProviderStatusBadge.svelte";
  import { Plus, ChevronRight } from "lucide-svelte";

  export let providers: ModelProviderPublic[] = [];
  export let selectedProviderId: string | null = null;

  const dispatch = createEventDispatcher<{
    select: { providerId: string | null; isNew: boolean; providerType: string };
  }>();

  // Provider types available for creation
  const providerTypes = [
    { type: "openai", label: "OpenAI", description: "OpenAI and compatible cloud APIs (Together, Groq, Fireworks)" },
    { type: "azure", label: "Azure OpenAI", description: "Enterprise Azure deployments" },
    { type: "anthropic", label: "Anthropic", description: "Claude 4, Claude 3.5" },
    { type: "gemini", label: "Google Gemini", description: "Gemini Pro, Gemini Flash" },
    { type: "cohere", label: "Cohere", description: "Command, Embed models" },
    { type: "mistral", label: "Mistral AI", description: "Mistral, Mixtral models" },
    { type: "vllm", label: "vLLM", description: "Self-hosted vLLM inference server" }
  ] as const;

  type ViewMode = "select" | "create";
  let viewMode: ViewMode = providers.length > 0 ? "select" : "create";

  // Selection state
  let hoveredProvider: string | null = null;
  let selectedNewProviderType: string | null = null;

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
              <span class="font-medium text-primary">{label}</span>
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
      </div>
    </div>
  {/if}
</div>
