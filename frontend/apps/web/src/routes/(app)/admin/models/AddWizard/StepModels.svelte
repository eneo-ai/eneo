<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Button, Input } from "@intric/ui";
  import { createEventDispatcher, onMount } from "svelte";
  import { m } from "$lib/paraglide/messages";
  import { ArrowLeft, Plus, Trash2, Sparkles, Check, ListPlus } from "lucide-svelte";
  import HelpTooltip from "../components/HelpTooltip.svelte";

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
    tokenLimit?: number;
    vision?: boolean;
    reasoning?: boolean;
    family?: string;
    dimensions?: number;
    maxInput?: number;
  }> = [];

  const dispatch = createEventDispatcher<{
    complete: { skip: boolean; pendingModel?: typeof currentModel };
    back: void;
  }>();

  // Model suggestions based on provider type
  const modelSuggestions: Record<string, Record<string, Array<{ name: string; displayName: string; tokenLimit?: number; vision?: boolean; reasoning?: boolean }>>> = {
    openai: {
      completion: [
        { name: "gpt-5.2", displayName: "GPT-5.2", tokenLimit: 200000, vision: true },
        { name: "gpt-5.1", displayName: "GPT-5.1", tokenLimit: 200000, vision: true, reasoning: true },
        { name: "gpt-5-mini", displayName: "GPT-5 Mini", tokenLimit: 128000, vision: true },
        { name: "gpt-4o", displayName: "GPT-4o", tokenLimit: 128000, vision: true },
        { name: "gpt-4o-mini", displayName: "GPT-4o Mini", tokenLimit: 128000, vision: true }
      ],
      embedding: [
        { name: "text-embedding-3-large", displayName: "Text Embedding 3 Large" },
        { name: "text-embedding-3-small", displayName: "Text Embedding 3 Small" },
        { name: "text-embedding-ada-002", displayName: "Ada 002" }
      ],
      transcription: [
        { name: "whisper-1", displayName: "Whisper" }
      ]
    },
    anthropic: {
      completion: [
        { name: "claude-opus-4-5-20251101", displayName: "Claude Opus 4.5", tokenLimit: 200000, vision: true, reasoning: true },
        { name: "claude-sonnet-4-20250514", displayName: "Claude Sonnet 4", tokenLimit: 200000, vision: true },
        { name: "claude-3-7-sonnet-20250219", displayName: "Claude 3.7 Sonnet", tokenLimit: 200000, vision: true, reasoning: true },
        { name: "claude-3-5-sonnet-20241022", displayName: "Claude 3.5 Sonnet", tokenLimit: 200000, vision: true },
        { name: "claude-3-5-haiku-20241022", displayName: "Claude 3.5 Haiku", tokenLimit: 200000, vision: true }
      ],
      embedding: [],
      transcription: []
    },
    gemini: {
      completion: [
        { name: "gemini-2.5-pro", displayName: "Gemini 2.5 Pro", tokenLimit: 1048576, vision: true, reasoning: true },
        { name: "gemini-2.5-flash", displayName: "Gemini 2.5 Flash", tokenLimit: 1048576, vision: true, reasoning: true },
        { name: "gemini-2.0-flash", displayName: "Gemini 2.0 Flash", tokenLimit: 1048576, vision: true },
        { name: "gemini-1.5-pro", displayName: "Gemini 1.5 Pro", tokenLimit: 2097152, vision: true },
        { name: "gemini-1.5-flash", displayName: "Gemini 1.5 Flash", tokenLimit: 1048576, vision: true }
      ],
      embedding: [
        { name: "text-embedding-004", displayName: "Text Embedding 004" }
      ],
      transcription: []
    },
    cohere: {
      completion: [
        { name: "command-r-plus", displayName: "Command R+", tokenLimit: 128000 },
        { name: "command-r", displayName: "Command R", tokenLimit: 128000 }
      ],
      embedding: [
        { name: "embed-english-v3.0", displayName: "Embed English v3" },
        { name: "embed-multilingual-v3.0", displayName: "Embed Multilingual v3" }
      ],
      transcription: []
    },
    mistral: {
      completion: [
        { name: "mistral-large-latest", displayName: "Mistral Large", tokenLimit: 128000 },
        { name: "mistral-medium-latest", displayName: "Mistral Medium", tokenLimit: 32000 },
        { name: "mistral-small-latest", displayName: "Mistral Small", tokenLimit: 32000 }
      ],
      embedding: [
        { name: "mistral-embed", displayName: "Mistral Embed" }
      ],
      transcription: []
    }
  };

  // Get suggestions for current provider and model type
  $: suggestions = modelSuggestions[providerType]?.[modelType] || [];

  // Current model being edited
  let currentModel = createEmptyModel();

  function createEmptyModel() {
    return {
      name: "",
      displayName: "",
      tokenLimit: 128000,
      vision: false,
      reasoning: false,
      family: "openai",
      dimensions: undefined as number | undefined,
      maxInput: undefined as number | undefined
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
      family: "openai",
      dimensions: undefined,
      maxInput: undefined
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
            class="rounded-full border border-dimmer px-3 py-1.5 text-sm transition-all duration-150
              hover:border-accent-default hover:bg-accent-dimmer
              focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent-default/60 focus-visible:ring-offset-1 focus-visible:ring-offset-surface"
            on:click={() => useSuggestion(suggestion)}
          >
            {suggestion.displayName}
          </button>
        {/each}
      </div>
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
