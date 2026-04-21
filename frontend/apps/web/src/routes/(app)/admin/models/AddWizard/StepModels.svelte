<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Button, Input } from "@intric/ui";
  import { createEventDispatcher, onMount } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import {
    ArrowLeft,
    Trash2,
    Sparkles,
    ListPlus,
    TriangleAlert,
    Search,
    Loader2,
    CircleCheck,
    CircleX,
    Zap
  } from "lucide-svelte";
  import HelpTooltip from "../components/HelpTooltip.svelte";
  import { getIntric } from "$lib/core/Intric";
  import { toast } from "$lib/components/toast";

  const intric = getIntric();

  import type { ModelProviderCapabilities } from "../modelProviderCapabilities";

  /** Capabilities loaded by parent (AddWizard) */
  export let capabilities: ModelProviderCapabilities | null = null;

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
    volcengine: "chn"
  };

  // Auto-focus first input on mount
  onMount(() => {
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
    maxInputTokens?: number;
    maxOutputTokens?: number;
    vision?: boolean;
    reasoning?: boolean;
    supportsToolCalling?: boolean;
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
    transcription: "transcription"
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

  // Extract provider map from capabilities for model lookups
  $: capabilityProviders = (capabilities?.providers ?? {}) as Record<
    string,
    { modes: string[]; models: Record<string, ModelInfo[]> }
  >;

  function formatTokens(limit: number): string {
    if (limit >= 1_000_000 || (limit >= 1_000 && Math.round(limit / 1_000) >= 1_000)) {
      const val = limit / 1_000_000;
      return `${val % 1 === 0 ? val.toFixed(0) : val.toFixed(1)}M`;
    }
    if (limit >= 1_000) return `${Math.round(limit / 1_000)}K`;
    return limit.toString();
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
      const result = (await intric.modelProviders.listModels({
        id: providerId
      })) as unknown as Record<string, unknown>[];
      if (
        result &&
        Array.isArray(result) &&
        result.length > 0 &&
        (result[0] as Record<string, unknown>)?.error
      ) {
        liveModelsError = (result[0] as Record<string, unknown>).error as string;
      } else if (result && Array.isArray(result)) {
        liveModels = result.map((item: Record<string, unknown>) => ({
          name: item.model ? `${item.name} (${item.model})` : String(item.name),
          max_input_tokens: undefined,
          max_output_tokens: undefined,
          supports_vision: false,
          supports_reasoning: false
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
      : ((capabilityProviders[providerType]?.models?.[modeMap[modelType]] ?? []) as ModelInfo[]);

  // Top 4 as quick suggestions (leaving room for "Browse all" chip)
  $: suggestions = allModels.slice(0, 4);

  // Self-hosted providers have no static model list — LiteLLM can't provide defaults
  $: isSelfHostedProvider =
    providerType !== "" &&
    providerType in capabilityProviders &&
    Object.keys(capabilityProviders[providerType]?.models ?? {}).length === 0;

  // Check if provider is known in LiteLLM but doesn't support this model type.
  // Unknown providers (e.g. vLLM, self-hosted) are not flagged — they can host any model type.
  $: providerHasNoSupport =
    providerType !== "" &&
    Object.keys(capabilityProviders).length > 0 &&
    providerType in capabilityProviders &&
    !capabilityProviders[providerType]?.modes?.includes(modeMap[modelType]);

  // Browse all models
  let showAllModels = false;
  let modelSearch = "";
  $: filteredModels = modelSearch
    ? allModels.filter((m) => m.name.toLowerCase().includes(modelSearch.toLowerCase()))
    : allModels;

  function selectModelInfo(info: ModelInfo) {
    currentModel.name = info.name;
    currentModel.displayName = info.name;
    if (modelType === "completion") {
      currentModel.maxInputTokensStr =
        info.max_input_tokens != null ? String(info.max_input_tokens) : "";
      currentModel.maxOutputTokensStr =
        info.max_output_tokens != null ? String(info.max_output_tokens) : "";
      currentModel.vision = info.supports_vision ?? false;
      currentModel.reasoning = info.supports_reasoning ?? false;
      currentModel.supportsToolCalling = info.supports_function_calling ?? false;
    } else if (modelType === "embedding") {
      currentModel.dimensionsStr =
        info.output_vector_size != null ? String(info.output_vector_size) : "";
      currentModel.maxInputStr = info.max_input_tokens != null ? String(info.max_input_tokens) : "";
    }
  }

  // Current model being edited
  let currentModel = createEmptyModel();

  function createEmptyModel() {
    return {
      name: "",
      displayName: "",
      maxInputTokensStr: "",
      maxOutputTokensStr: "",
      vision: false,
      reasoning: false,
      supportsToolCalling: false,
      family: modelType === "embedding" ? "openai" : providerType || "openai",
      dimensionsStr: "",
      maxInputStr: "",
      hosting: providerDefaultHosting[providerType] ?? "swe"
    };
  }

  function addModel() {
    if (!currentModel.name.trim() || !currentModel.displayName.trim()) return;

    const maxInputTokens = currentModel.maxInputTokensStr
      ? parseInt(currentModel.maxInputTokensStr, 10)
      : undefined;
    const maxOutputTokens = currentModel.maxOutputTokensStr
      ? parseInt(currentModel.maxOutputTokensStr, 10)
      : undefined;
    const dimensions = currentModel.dimensionsStr
      ? parseInt(currentModel.dimensionsStr, 10)
      : undefined;
    const maxInput = currentModel.maxInputStr ? parseInt(currentModel.maxInputStr, 10) : undefined;

    models = [
      ...models,
      {
        name: currentModel.name,
        displayName: currentModel.displayName,
        maxInputTokens,
        maxOutputTokens,
        vision: currentModel.vision,
        reasoning: currentModel.reasoning,
        supportsToolCalling: currentModel.supportsToolCalling,
        family: currentModel.family,
        dimensions,
        maxInput,
        hosting: currentModel.hosting
      }
    ];
    currentModel = createEmptyModel();
  }

  // Validation state per model index
  type ValidationState = { status: "idle" | "testing" | "success" | "error"; message?: string };
  let validationStates: Record<number, ValidationState> = {};

  async function testModel(index: number) {
    if (!providerId) return;
    const model = models[index];
    if (!model) return;

    validationStates[index] = { status: "testing" };
    validationStates = validationStates;

    try {
      const result = await intric.modelProviders.validateModel(
        { id: providerId },
        { model_name: model.name, model_type: modelType }
      );
      if (result.success) {
        validationStates[index] = { status: "success", message: m.model_test_success() };
      } else {
        validationStates[index] = {
          status: "error",
          message: result.error || m.model_test_failed()
        };
      }
    } catch {
      validationStates[index] = { status: "error", message: m.model_test_connection_error() };
    }
    validationStates = validationStates;
  }

  function removeModel(index: number) {
    models = models.filter((_, i) => i !== index);
    // Re-index validation states
    const newStates: Record<number, ValidationState> = {};
    for (const [key, val] of Object.entries(validationStates)) {
      const k = Number(key);
      if (k < index) newStates[k] = val;
      else if (k > index) newStates[k - 1] = val;
    }
    validationStates = newStates;
  }

  function handleSkip() {
    dispatch("complete", { skip: true });
  }

  function handleBack() {
    dispatch("back");
  }

  let isLookingUpDefaults = false;
  async function lookupDefaults() {
    if (!currentModel.name.trim()) return;
    isLookingUpDefaults = true;
    try {
      const result = await intric.modelProviders.getModelDefaults(currentModel.name.trim());
      if (result.found) {
        if (result.max_input_tokens != null)
          currentModel.maxInputTokensStr = String(result.max_input_tokens);
        if (result.max_output_tokens != null)
          currentModel.maxOutputTokensStr = String(result.max_output_tokens);
        currentModel.vision = result.supports_vision ?? false;
        currentModel.reasoning = result.supports_reasoning ?? false;
        currentModel.supportsToolCalling = result.supports_function_calling ?? false;
        toast.success(m.reset_to_defaults_success());
      } else {
        toast.info(m.reset_to_defaults_not_found({ model: currentModel.name.trim() }));
      }
    } catch {
      toast.info(m.reset_to_defaults_not_found({ model: currentModel.name.trim() }));
    } finally {
      isLookingUpDefaults = false;
    }
  }

  $: canAddModel =
    currentModel.name.trim() !== "" &&
    currentModel.displayName.trim() !== "" &&
    (modelType !== "completion" ||
      (currentModel.maxInputTokensStr !== "" &&
        parseInt(currentModel.maxInputTokensStr, 10) > 0 &&
        currentModel.maxOutputTokensStr !== "" &&
        parseInt(currentModel.maxOutputTokensStr, 10) > 0));

  // Export for parent to bind and track
  export let canFinish = false;
  $: canFinish = models.length > 0 || canAddModel;

  // Export pending model for parent to check
  export function getPendingModel() {
    if (canAddModel) {
      return {
        name: currentModel.name,
        displayName: currentModel.displayName,
        maxInputTokens: currentModel.maxInputTokensStr
          ? parseInt(currentModel.maxInputTokensStr, 10)
          : undefined,
        maxOutputTokens: currentModel.maxOutputTokensStr
          ? parseInt(currentModel.maxOutputTokensStr, 10)
          : undefined,
        vision: currentModel.vision,
        reasoning: currentModel.reasoning,
        supportsToolCalling: currentModel.supportsToolCalling,
        family: currentModel.family,
        dimensions: currentModel.dimensionsStr
          ? parseInt(currentModel.dimensionsStr, 10)
          : undefined,
        maxInput: currentModel.maxInputStr ? parseInt(currentModel.maxInputStr, 10) : undefined,
        hosting: currentModel.hosting
      };
    }
    return null;
  }
</script>

<div class="flex flex-col gap-6">
  <!-- Header -->
  <div>
    <h3 class="text-primary font-medium">{m.add_models()}</h3>
    <p class="text-muted text-sm">{m.add_models_description()}</p>
  </div>

  <!-- Warning when provider doesn't support this model type -->
  {#if providerHasNoSupport}
    <div
      class="border-label-default bg-label-dimmer label-warning flex items-start gap-3 rounded-lg border px-4 py-3 text-sm"
    >
      <TriangleAlert class="text-label-stronger mt-0.5 h-5 w-5 flex-shrink-0" />
      <div>
        <p class="text-label-stronger font-medium">
          {m.provider_no_support_title({ providerType, modelType })}
        </p>
        <p class="text-label-default mt-0.5">{m.provider_no_support_description()}</p>
      </div>
    </div>
  {/if}

  <!-- Error fetching live models -->
  {#if liveModelsError}
    <div class="border-dimmer bg-surface-dimmer text-muted rounded-lg border px-4 py-3 text-sm">
      <p>{liveModelsError}</p>
      <p class="mt-1">{m.enter_model_manually()}</p>
    </div>
  {/if}

  <!-- Suggestions (if available) -->
  {#if suggestions.length > 0}
    <div class="flex flex-col gap-3">
      <div class="text-muted flex items-center gap-2 text-sm">
        <Sparkles class="h-4 w-4" />
        <span>{m.suggested_models()}</span>
      </div>

      <div class="flex flex-wrap gap-2">
        {#each suggestions as suggestion (suggestion.name)}
          <button
            type="button"
            class="rounded-full border px-3 py-1.5 text-sm transition-all duration-150
              {currentModel.name === suggestion.name
              ? 'border-accent-default bg-accent-dimmer text-accent-stronger'
              : 'border-dimmer hover:border-accent-default hover:bg-accent-dimmer'}
              focus-visible:ring-accent-default/60 focus-visible:ring-offset-surface focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:outline-none"
            on:click={() => selectModelInfo(suggestion)}
          >
            {suggestion.name}
          </button>
        {/each}
        {#if allModels.length > 4}
          <button
            type="button"
            class="border-dimmer hover:border-accent-default hover:bg-accent-dimmer focus-visible:ring-accent-default/60 focus-visible:ring-offset-surface flex items-center gap-1.5
              rounded-full border
              px-3 py-1.5 text-sm transition-all duration-150
              focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:outline-none"
            on:click={() => {
              showAllModels = !showAllModels;
              modelSearch = "";
            }}
          >
            <Search class="h-3.5 w-3.5" />
            {showAllModels ? m.close() : m.browse_all()}
          </button>
        {/if}
      </div>

      {#if showAllModels}
        <div class="border-dimmer bg-surface-dimmer flex flex-col gap-2 rounded-lg border p-3">
          <input
            type="text"
            bind:value={modelSearch}
            placeholder={m.search_models()}
            class="border-dimmer bg-surface text-primary placeholder:text-muted focus:border-accent-default focus:ring-accent-default w-full rounded-md border
              px-3 py-2 text-sm focus:ring-1 focus:outline-none"
          />
          <div class="flex max-h-48 flex-col gap-1 overflow-y-auto">
            {#each filteredModels as model (model.name)}
              <button
                type="button"
                class="w-full rounded-md px-3 py-2 text-left text-sm transition-all duration-100
                  {currentModel.name === model.name
                  ? 'bg-accent-dimmer text-accent-stronger'
                  : 'text-primary hover:bg-hover'}
                  focus-visible:ring-accent-default/60 focus-visible:ring-2 focus-visible:outline-none"
                on:click={() => {
                  selectModelInfo(model);
                  showAllModels = false;
                }}
              >
                <span class="font-medium">{model.name}</span>
                <span class="text-muted mt-0.5 flex gap-3 text-xs">
                  {#if model.max_input_tokens}
                    <span>{formatTokens(model.max_input_tokens)} context</span>
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
              <p class="text-muted px-3 py-2 text-sm">{m.no_models_found()}</p>
            {/if}
          </div>
        </div>
      {/if}
    </div>
  {/if}

  <!-- Model Form -->
  <form on:submit|preventDefault={addModel} class="flex flex-col gap-4">
    <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
      <!-- Model Identifier -->
      <div class="flex flex-col gap-2">
        <label for="model-name" class="flex items-center gap-1.5 text-sm font-medium">
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
        {#if modelType === "completion" && currentModel.name.trim() && !isSelfHostedProvider}
          <button
            type="button"
            class="text-accent-default hover:text-accent-stronger flex items-center gap-1 self-start text-xs underline underline-offset-2 transition-colors disabled:cursor-not-allowed disabled:opacity-50"
            disabled={isLookingUpDefaults}
            on:click={lookupDefaults}
          >
            {#if isLookingUpDefaults}
              <Loader2 class="h-3 w-3 animate-spin" />
            {/if}
            {m.lookup_defaults()}
          </button>
        {/if}
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
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <div class="flex flex-col gap-2">
          <label for="max-input-tokens" class="flex items-center gap-1.5 text-sm font-medium">
            {m.max_input_tokens()}
            <HelpTooltip text={m.max_input_tokens_help()} />
          </label>
          <Input.Text
            id="max-input-tokens"
            type="number"
            bind:value={currentModel.maxInputTokensStr}
            placeholder={m.max_input_tokens()}
            min="1024"
            max="10000000"
          />
          <p class="text-muted text-xs">{m.token_reference_input()}</p>
        </div>

        <div class="flex flex-col gap-2">
          <label for="max-output-tokens" class="flex items-center gap-1.5 text-sm font-medium">
            {m.max_output_tokens()}
            <HelpTooltip text={m.max_output_tokens_help()} />
          </label>
          <Input.Text
            id="max-output-tokens"
            type="number"
            bind:value={currentModel.maxOutputTokensStr}
            placeholder={m.max_output_tokens()}
            min="1"
            max="10000000"
          />
          <p class="text-muted text-xs">{m.token_reference_output()}</p>
        </div>
      </div>

      <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div class="col-span-3 flex items-center gap-6">
          <label class="flex cursor-pointer items-center gap-2 text-sm">
            <input
              type="checkbox"
              bind:checked={currentModel.vision}
              class="accent-accent-default h-4 w-4 rounded"
            />
            <span class="flex items-center gap-1">
              {m.vision_support()}
              <HelpTooltip text={m.vision_help()} />
            </span>
          </label>

          <label class="flex cursor-pointer items-center gap-2 text-sm">
            <input
              type="checkbox"
              bind:checked={currentModel.reasoning}
              class="accent-accent-default h-4 w-4 rounded"
            />
            <span class="flex items-center gap-1">
              {m.reasoning_support()}
              <HelpTooltip text={m.reasoning_help()} />
            </span>
          </label>

          <label class="flex cursor-pointer items-center gap-2 text-sm">
            <input
              type="checkbox"
              bind:checked={currentModel.supportsToolCalling}
              class="accent-accent-default h-4 w-4 rounded"
            />
            <span class="flex items-center gap-1">
              {m.tool_calling_support()}
              <HelpTooltip text={m.tool_calling_help()} />
            </span>
          </label>
        </div>
      </div>
    {/if}

    <!-- Embedding-specific fields -->
    {#if modelType === "embedding"}
      <div class="grid grid-cols-1 gap-4 sm:grid-cols-3">
        <div class="flex flex-col gap-2">
          <label for="model-family" class="flex items-center gap-1.5 text-sm font-medium">
            {m.model_family()}
            <HelpTooltip text={m.model_family_help()} />
          </label>
          <select
            id="model-family"
            bind:value={currentModel.family}
            class="border-dimmer bg-surface text-primary focus:border-accent-default focus:ring-accent-default h-10 rounded-md border
              px-3 text-sm focus:ring-1 focus:outline-none"
          >
            <option value="openai">OpenAI (Standard)</option>
            <option value="e5">E5 (HuggingFace)</option>
          </select>
        </div>

        <div class="flex flex-col gap-2">
          <label for="dimensions" class="flex items-center gap-1.5 text-sm font-medium">
            {m.dimensions()}
            <HelpTooltip text={m.dimensions_help()} />
          </label>
          <Input.Text
            id="dimensions"
            type="number"
            bind:value={currentModel.dimensionsStr}
            placeholder="1536"
          />
        </div>

        <div class="flex flex-col gap-2">
          <label for="max-input" class="text-sm font-medium">{m.max_input_tokens()}</label>
          <Input.Text
            id="max-input"
            type="number"
            bind:value={currentModel.maxInputStr}
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
        class="border-dimmer bg-surface text-primary focus:border-accent-default focus:ring-accent-default h-10 rounded-md border
          px-3 text-sm focus:ring-1 focus:outline-none"
      >
        {#each hostingOptions as option (option.value)}
          <option value={option.value}>{option.label}</option>
        {/each}
      </select>
    </div>

    <!-- Action Buttons -->
    <div class="border-dimmer/40 mt-2 border-t pt-4">
      <div class="flex items-center gap-3">
        <Button
          type="submit"
          variant="simple"
          class="text-muted hover:text-primary focus-visible:ring-accent-default/70 focus-visible:ring-offset-surface gap-2 focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:!outline-none"
          disabled={!canAddModel}
        >
          <ListPlus class="h-4 w-4" />
          {m.add_another_model()}
        </Button>
        {#if canAddModel && models.length === 0}
          <span class="text-muted text-xs">
            {m.or_click_finish_directly()}
          </span>
        {/if}
      </div>
    </div>
  </form>

  <!-- Added Models List -->
  {#if models.length > 0}
    <div class="flex flex-col gap-2">
      <h4 class="text-muted text-sm font-medium">
        {models.length === 1
          ? m.models_to_add_one({ count: models.length })
          : m.models_to_add_other({ count: models.length })}
      </h4>

      <div class="flex flex-col gap-2">
        {#each models as model, index (index)}
          {@const vs = validationStates[index] ?? { status: "idle" }}
          <div
            class="border-dimmer bg-surface flex items-center justify-between rounded-lg border p-3"
          >
            <div class="flex min-w-0 flex-1 flex-col">
              <span class="text-primary font-medium">{model.displayName}</span>
              <span class="text-muted text-sm">{model.name}</span>
              {#if vs.status === "error" && vs.message}
                <span class="text-negative-default mt-1 text-xs">{vs.message}</span>
              {/if}
            </div>

            <div class="ml-2 flex flex-shrink-0 items-center gap-1">
              {#if vs.status === "testing"}
                <div class="text-muted p-2">
                  <Loader2 class="h-4 w-4 animate-spin" />
                </div>
              {:else if vs.status === "success"}
                <div class="text-positive-default p-2" title={vs.message}>
                  <CircleCheck class="h-4 w-4" />
                </div>
              {:else if vs.status === "error"}
                <div class="text-negative-default p-2" title={vs.message}>
                  <CircleX class="h-4 w-4" />
                </div>
              {/if}

              <Button
                variant="simple"
                padding="icon"
                on:click={() => testModel(index)}
                disabled={vs.status === "testing" || !providerId}
                class="text-muted hover:text-accent-default focus-visible:ring-accent-default/70 focus-visible:ring-offset-surface focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:!outline-none"
                title={m.test_model()}
              >
                <Zap class="h-4 w-4" />
              </Button>

              <Button
                variant="simple"
                padding="icon"
                on:click={() => removeModel(index)}
                class="text-muted hover:text-negative-default focus-visible:ring-negative-default/70 focus-visible:ring-offset-surface focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:!outline-none"
              >
                <Trash2 class="h-4 w-4" />
              </Button>
            </div>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  <!-- Navigation -->
  <div class="border-dimmer flex items-center justify-between border-t pt-4">
    <div class="flex items-center gap-4">
      <Button
        variant="simple"
        on:click={handleBack}
        class="focus-visible:ring-accent-default/70 focus-visible:ring-offset-surface gap-2 focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:!outline-none"
      >
        <ArrowLeft class="h-4 w-4" />
        {m.back()}
      </Button>

      <span class="text-muted/70 text-sm">
        {#if models.length === 0 && !canAddModel}
          {m.add_at_least_one_model()}
        {:else if models.length === 0 && canAddModel}
          <span class="text-positive-default">{m.model_ready_to_add()}</span>
        {:else}
          {models.length === 1
            ? m.models_ready_one({ count: models.length })
            : m.models_ready_other({ count: models.length })}
        {/if}
      </span>
    </div>

    <button
      type="button"
      class="text-muted hover:text-primary decoration-muted/50 focus-visible:text-primary focus-visible:ring-accent-default/60 focus-visible:ring-offset-surface rounded-sm text-sm underline
        underline-offset-2 transition-colors duration-150 focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:outline-none"
      on:click={handleSkip}
    >
      {m.skip_for_now()}
    </button>
  </div>
</div>
