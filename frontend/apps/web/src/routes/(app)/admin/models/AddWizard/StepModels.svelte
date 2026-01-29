<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Button, Input } from "@intric/ui";
  import { createEventDispatcher, onMount } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { ArrowLeft, Plus, Trash2, Sparkles, Check, ListPlus, TriangleAlert, Search } from "lucide-svelte";
  import HelpTooltip from "../components/HelpTooltip.svelte";
  import { getIntric } from "$lib/core/Intric";

  const intric = getIntric();

  // Hosting location options
  const hostingOptions = [
    { value: "swe", label: m.hosting_swe() },
    { value: "eu", label: m.hosting_eu() },
    { value: "usa", label: m.hosting_usa() },
    { value: "chn", label: m.hosting_chn() },
    { value: "can", label: m.hosting_can() },
    { value: "gbr", label: m.hosting_gbr() },
    { value: "isr", label: m.hosting_isr() },
    { value: "kor", label: m.hosting_kor() },
    { value: "deu", label: m.hosting_deu() },
    { value: "fra", label: m.hosting_fra() },
    { value: "jpn", label: m.hosting_jpn() }
  ] as const;

  // Default hosting region per provider type
  const providerDefaultHosting: Record<string, string> = {
    openai: "usa",
    anthropic: "usa",
    gemini: "usa",
    google: "usa",
    cohere: "can",
    mistral: "fra",
    deepseek: "chn",
    ai21: "isr",
    friendliai: "kor",
    aleph_alpha: "deu",
    nscale: "gbr",
    zhipuai: "chn",
    moonshot: "chn",
    baidu: "chn",
    volcengine: "chn",
  };

  // Auto-focus first input on mount
  onMount(() => {
    loadCapabilities();
    setTimeout(() => {
      const input = document.getElementById("model-name") as HTMLInputElement;
      input?.focus();
    }, 100);
  });

  export let modelType: "completion" | "embedding" | "transcription" = "completion";
  export let providerType: string;
  export let providerId: string | null;
  export let models: Array<{
    name: string;
    displayName: string;
    tokenLimit?: number;
    vision?: boolean;
    reasoning?: boolean;
    family?: string;
    dimensions?: number;
    maxInput?: number;
    hosting?: string;
  }> = [];

  const dispatch = createEventDispatcher<{
    complete: { skip: boolean; pendingModel?: typeof currentModel };
    back: void;
  }>();

  // LiteLLM mode mapping
  const modeMap: Record<string, string> = {
    completion: "completion",
    embedding: "embedding",
    transcription: "transcription",
  };

  // Model info from capabilities API
  interface ModelInfo {
    name: string;
    max_input_tokens?: number;
    max_output_tokens?: number;
    supports_vision?: boolean;
    supports_function_calling?: boolean;
    supports_reasoning?: boolean;
    output_vector_size?: number;
  }

  // Dynamic capabilities from LiteLLM
  let capabilities: Record<string, { modes: string[], models: Record<string, ModelInfo[]> }> = {};
  async function loadCapabilities() {
    try {
      capabilities = await intric.modelProviders.getCapabilities();
    } catch {
      // Silently fail — fall back to no suggestions
    }
  }

  // Providers that need live model listing from their API (not LiteLLM static data)
  const liveListProviders = new Set(["vllm"]);

  // Providers where LiteLLM names don't match user input (e.g. Azure uses deployment names)
  const noSuggestionsProviders = new Set(["azure"]);

  // Live models fetched from the provider's own API
  let liveModels: ModelInfo[] = [];
  let liveModelsLoaded = false;
  let liveModelsError = "";
  async function loadLiveModels() {
    if (!providerId || liveModelsLoaded) return;
    liveModelsError = "";
    try {
      const result = await intric.modelProviders.listModels({ id: providerId });
      if (result && Array.isArray(result) && result.length > 0 && result[0]?.error) {
        liveModelsError = result[0].error;
      } else if (result && Array.isArray(result)) {
        liveModels = result.map((m: any) => ({
          name: m.model ? `${m.name} (${m.model})` : m.name,
          max_input_tokens: undefined,
          max_output_tokens: undefined,
          supports_vision: false,
          supports_reasoning: false,
        }));
      }
    } catch {
      liveModelsError = "Could not fetch models from provider";
    }
    liveModelsLoaded = true;
  }
  $: if (liveListProviders.has(providerType) && providerId) loadLiveModels();

  // All models: live from provider API, static from LiteLLM, or none for Azure
  $: allModels = noSuggestionsProviders.has(providerType)
    ? []
    : liveListProviders.has(providerType)
      ? liveModels
      : (capabilities[providerType]?.models?.[modeMap[modelType]] ?? []) as ModelInfo[];

  // Top 4 as quick suggestions (leaving room for "Browse all" chip)
  $: suggestions = allModels.slice(0, 4);

  // Check if provider is known in LiteLLM but doesn't support this model type.
  // Unknown providers (e.g. vLLM, self-hosted) are not flagged — they can host any model type.
  $: providerHasNoSupport = providerType !== ""
    && Object.keys(capabilities).length > 0
    && providerType in capabilities
    && !capabilities[providerType]?.modes?.includes(modeMap[modelType]);

  // Browse all models
  let showAllModels = false;
  let modelSearch = "";
  $: filteredModels = modelSearch
    ? allModels.filter(m => m.name.toLowerCase().includes(modelSearch.toLowerCase()))
    : allModels;

  function selectModelInfo(info: ModelInfo) {
    currentModel.name = info.name;
    currentModel.displayName = info.name;
    if (modelType === "completion") {
      currentModel.tokenLimit = info.max_input_tokens ?? 128000;
      currentModel.vision = info.supports_vision ?? false;
      currentModel.reasoning = info.supports_reasoning ?? false;
    } else if (modelType === "embedding") {
      currentModel.dimensions = info.output_vector_size;
      currentModel.maxInput = info.max_input_tokens;
    }
  }

  // Current model being edited
  let currentModel = createEmptyModel();

  function createEmptyModel() {
    return {
      name: "",
      displayName: "",
      tokenLimit: 128000,
      vision: false,
      reasoning: false,
      family: modelType === "embedding" ? "openai" : (providerType || "openai"),
      dimensions: undefined as number | undefined,
      maxInput: undefined as number | undefined,
      hosting: providerDefaultHosting[providerType] ?? "swe"
    };
  }

  function addModel() {
    if (!currentModel.name.trim() || !currentModel.displayName.trim()) return;

    models = [...models, { ...currentModel }];
    currentModel = createEmptyModel();
  }

  function removeModel(index: number) {
    models = models.filter((_, i) => i !== index);
  }

  function useSuggestion(suggestion: typeof suggestions[0]) {
    currentModel = {
      name: suggestion.name,
      displayName: suggestion.displayName,
      tokenLimit: suggestion.tokenLimit ?? 128000,
      vision: suggestion.vision ?? false,
      reasoning: suggestion.reasoning ?? false,
      family: modelType === "embedding" ? "openai" : (providerType || "openai"),
      dimensions: undefined,
      maxInput: undefined,
      hosting: providerDefaultHosting[providerType] ?? "swe"
    };
  }

  function handleSkip() {
    dispatch("complete", { skip: true });
  }

  function handleBack() {
    dispatch("back");
  }

  $: canAddModel = currentModel.name.trim() !== "" && currentModel.displayName.trim() !== "";

  // Export for parent to bind and track
  export let canFinish = false;
  $: canFinish = models.length > 0 || canAddModel;

  // Export pending model for parent to check
  export function getPendingModel() {
    if (canAddModel) {
      return { ...currentModel };
    }
    return null;
  }
</script>

<div class="flex flex-col gap-6">
  <!-- Header -->
  <div>
    <h3 class="font-medium text-primary">{m.add_models()}</h3>
    <p class="text-sm text-muted">{m.add_models_description()}</p>
  </div>

  <!-- Warning when provider doesn't support this model type -->
  {#if providerHasNoSupport}
    <div class="flex items-start gap-3 rounded-lg border border-label-default bg-label-dimmer px-4 py-3 text-sm label-warning">
      <TriangleAlert class="h-5 w-5 flex-shrink-0 text-label-stronger mt-0.5" />
      <div>
        <p class="font-medium text-label-stronger">{m.provider_no_support_title({ providerType, modelType })}</p>
        <p class="text-label-default mt-0.5">{m.provider_no_support_description()}</p>
      </div>
    </div>
  {/if}

  <!-- Error fetching live models -->
  {#if liveModelsError}
    <div class="rounded-lg border border-dimmer bg-surface-dimmer px-4 py-3 text-sm text-muted">
      <p>{liveModelsError}</p>
      <p class="mt-1">{m.enter_model_manually()}</p>
    </div>
  {/if}

  <!-- Suggestions (if available) -->
  {#if suggestions.length > 0}
    <div class="flex flex-col gap-3">
      <div class="flex items-center gap-2 text-sm text-muted">
        <Sparkles class="h-4 w-4" />
        <span>{m.suggested_models()}</span>
      </div>

      <div class="flex flex-wrap gap-2">
        {#each suggestions as suggestion}
          <button
            type="button"
            class="rounded-full border px-3 py-1.5 text-sm transition-all duration-150
              {currentModel.name === suggestion.name
                ? 'border-accent-default bg-accent-dimmer text-accent-stronger'
                : 'border-dimmer hover:border-accent-default hover:bg-accent-dimmer'}
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-default/60 focus-visible:ring-offset-1 focus-visible:ring-offset-surface"
            on:click={() => selectModelInfo(suggestion)}
          >
            {suggestion.name}
          </button>
        {/each}
        {#if allModels.length > 4}
          <button
            type="button"
            class="rounded-full border border-dimmer px-3 py-1.5 text-sm transition-all duration-150
              hover:border-accent-default hover:bg-accent-dimmer
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-default/60 focus-visible:ring-offset-1 focus-visible:ring-offset-surface
              flex items-center gap-1.5"
            on:click={() => { showAllModels = !showAllModels; modelSearch = ""; }}
          >
            <Search class="h-3.5 w-3.5" />
            {showAllModels ? m.close() : m.browse_all()}
          </button>
        {/if}
      </div>

      {#if showAllModels}
        <div class="rounded-lg border border-dimmer bg-surface-dimmer p-3 flex flex-col gap-2">
          <input
            type="text"
            bind:value={modelSearch}
            placeholder={m.search_models()}
            class="w-full rounded-md border border-dimmer bg-surface px-3 py-2 text-sm text-primary
              placeholder:text-muted focus:border-accent-default focus:outline-none focus:ring-1 focus:ring-accent-default"
          />
          <div class="max-h-48 overflow-y-auto flex flex-col gap-1">
            {#each filteredModels as model}
              <button
                type="button"
                class="w-full text-left rounded-md px-3 py-2 text-sm transition-all duration-100
                  {currentModel.name === model.name
                    ? 'bg-accent-dimmer text-accent-stronger'
                    : 'text-primary hover:bg-hover'}
                  focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-default/60"
                on:click={() => { selectModelInfo(model); showAllModels = false; }}
              >
                <span class="font-medium">{model.name}</span>
                <span class="flex gap-3 text-xs text-muted mt-0.5">
                  {#if model.max_input_tokens}
                    <span>{(model.max_input_tokens / 1000).toFixed(0)}K context</span>
                  {/if}
                  {#if model.supports_vision}
                    <span>Vision</span>
                  {/if}
                  {#if model.supports_reasoning}
                    <span>Reasoning</span>
                  {/if}
                  {#if model.output_vector_size}
                    <span>{model.output_vector_size}d</span>
                  {/if}
                </span>
              </button>
            {/each}
            {#if filteredModels.length === 0}
              <p class="text-sm text-muted px-3 py-2">{m.no_models_found()}</p>
            {/if}
          </div>
        </div>
      {/if}
    </div>
  {/if}

  <!-- Model Form -->
  <form on:submit|preventDefault={addModel} class="flex flex-col gap-4">
    <div class="grid grid-cols-1 sm:grid-cols-2 gap-4">
      <!-- Model Identifier -->
      <div class="flex flex-col gap-2">
        <label for="model-name" class="text-sm font-medium flex items-center gap-1.5">
          {m.model_identifier()}
          <HelpTooltip text={m.model_identifier_help()} />
        </label>
        <Input.Text
          id="model-name"
          bind:value={currentModel.name}
          placeholder={modelType === "completion"
            ? m.model_identifier_placeholder_completion()
            : modelType === "embedding"
              ? m.model_identifier_placeholder_embedding()
              : m.model_identifier_placeholder_transcription()}
        />
      </div>

      <!-- Display Name -->
      <div class="flex flex-col gap-2">
        <label for="display-name" class="text-sm font-medium">{m.display_name()}</label>
        <Input.Text
          id="display-name"
          bind:value={currentModel.displayName}
          placeholder={m.display_name_placeholder_completion()}
        />
      </div>
    </div>

    <!-- Completion-specific fields -->
    {#if modelType === "completion"}
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div class="flex flex-col gap-2">
          <label for="token-limit" class="text-sm font-medium flex items-center gap-1.5">
            {m.token_limit()}
            <HelpTooltip text={m.token_limit_help()} />
          </label>
          <Input.Text
            id="token-limit"
            type="number"
            bind:value={currentModel.tokenLimit}
            min="1024"
            max="10000000"
          />
        </div>

        <div class="flex items-center gap-6 col-span-2">
          <label class="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              bind:checked={currentModel.vision}
              class="rounded accent-accent-default h-4 w-4"
            />
            <span class="flex items-center gap-1">
              {m.vision_support()}
              <HelpTooltip text={m.vision_help()} />
            </span>
          </label>

          <label class="flex items-center gap-2 text-sm cursor-pointer">
            <input
              type="checkbox"
              bind:checked={currentModel.reasoning}
              class="rounded accent-accent-default h-4 w-4"
            />
            <span class="flex items-center gap-1">
              {m.reasoning_support()}
              <HelpTooltip text={m.reasoning_help()} />
            </span>
          </label>
        </div>
      </div>
    {/if}

    <!-- Embedding-specific fields -->
    {#if modelType === "embedding"}
      <div class="grid grid-cols-1 sm:grid-cols-3 gap-4">
        <div class="flex flex-col gap-2">
          <label for="model-family" class="text-sm font-medium flex items-center gap-1.5">
            {m.model_family()}
            <HelpTooltip text={m.model_family_help()} />
          </label>
          <select
            id="model-family"
            bind:value={currentModel.family}
            class="h-10 rounded-md border border-dimmer bg-surface px-3 text-sm text-primary
              focus:border-accent-default focus:outline-none focus:ring-1 focus:ring-accent-default"
          >
            <option value="openai">OpenAI (Standard)</option>
            <option value="e5">E5 (HuggingFace)</option>
          </select>
        </div>

        <div class="flex flex-col gap-2">
          <label for="dimensions" class="text-sm font-medium flex items-center gap-1.5">
            {m.dimensions()}
            <HelpTooltip text={m.dimensions_help()} />
          </label>
          <Input.Text
            id="dimensions"
            type="number"
            bind:value={currentModel.dimensions}
            placeholder="1536"
          />
        </div>

        <div class="flex flex-col gap-2">
          <label for="max-input" class="text-sm font-medium">{m.max_input_tokens()}</label>
          <Input.Text
            id="max-input"
            type="number"
            bind:value={currentModel.maxInput}
            placeholder="8191"
          />
        </div>
      </div>
    {/if}

    <!-- Hosting Location (common to all model types) -->
    <div class="flex flex-col gap-2">
      <label for="hosting" class="text-sm font-medium">{m.hosting_region()}</label>
      <select
        id="hosting"
        bind:value={currentModel.hosting}
        class="h-10 rounded-md border border-dimmer bg-surface px-3 text-sm text-primary
          focus:border-accent-default focus:outline-none focus:ring-1 focus:ring-accent-default"
      >
        {#each hostingOptions as option}
          <option value={option.value}>{option.label}</option>
        {/each}
      </select>
    </div>

    <!-- Action Buttons -->
    <div class="border-t border-dimmer/40 pt-4 mt-2">
      <div class="flex items-center gap-3">
        <Button
          type="submit"
          variant="ghost"
          class="gap-2 text-muted hover:text-primary focus-visible:!outline-none focus-visible:ring-2 focus-visible:ring-accent-default/70 focus-visible:ring-offset-1 focus-visible:ring-offset-surface"
          disabled={!canAddModel}
        >
          <ListPlus class="h-4 w-4" />
          {m.add_another_model()}
        </Button>
        {#if canAddModel && models.length === 0}
          <span class="text-xs text-muted">
            {m.or_click_finish_directly()}
          </span>
        {/if}
      </div>
    </div>
  </form>

  <!-- Added Models List -->
  {#if models.length > 0}
    <div class="flex flex-col gap-2">
      <h4 class="text-sm font-medium text-muted">
        {models.length === 1 ? m.models_to_add_one({ count: models.length }) : m.models_to_add_other({ count: models.length })}
      </h4>

      <div class="flex flex-col gap-2">
        {#each models as model, index}
          <div class="flex items-center justify-between rounded-lg border border-dimmer bg-surface p-3">
            <div class="flex flex-col">
              <span class="font-medium text-primary">{model.displayName}</span>
              <span class="text-sm text-muted">{model.name}</span>
            </div>

            <Button
              variant="ghost"
              padding="icon"
              on:click={() => removeModel(index)}
              class="text-muted hover:text-negative-default focus-visible:!outline-none focus-visible:ring-2 focus-visible:ring-negative-default/70 focus-visible:ring-offset-1 focus-visible:ring-offset-surface"
            >
              <Trash2 class="h-4 w-4" />
            </Button>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  <!-- Navigation -->
  <div class="flex items-center justify-between border-t border-dimmer pt-4">
    <div class="flex items-center gap-4">
      <Button variant="ghost" on:click={handleBack} class="gap-2 focus-visible:!outline-none focus-visible:ring-2 focus-visible:ring-accent-default/70 focus-visible:ring-offset-1 focus-visible:ring-offset-surface">
        <ArrowLeft class="h-4 w-4" />
        {m.back()}
      </Button>

      <span class="text-sm text-muted/70">
        {#if models.length === 0 && !canAddModel}
          {m.add_at_least_one_model()}
        {:else if models.length === 0 && canAddModel}
          <span class="text-positive-default">{m.model_ready_to_add()}</span>
        {:else}
          {models.length === 1 ? m.models_ready_one({ count: models.length }) : m.models_ready_other({ count: models.length })}
        {/if}
      </span>
    </div>

    <button
      type="button"
      class="text-sm text-muted hover:text-primary transition-colors duration-150 underline decoration-muted/50 underline-offset-2 rounded-sm
        focus-visible:outline-none focus-visible:text-primary focus-visible:ring-2 focus-visible:ring-accent-default/60 focus-visible:ring-offset-1 focus-visible:ring-offset-surface"
      on:click={handleSkip}
    >
      {m.skip_for_now()}
    </button>
  </div>
</div>
