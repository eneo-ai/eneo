<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type {
    CompletionModel,
    EmbeddingModel,
    TranscriptionModel,
    TenantCompletionModelUpdate,
    TenantEmbeddingModelUpdate,
    TenantTranscriptionModelUpdate
  } from "@intric/intric-js";
  import { Button, Dialog, Input } from "@intric/ui";
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { writable, type Writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import { Loader2 } from "lucide-svelte";
  import { toast } from "$lib/components/toast";

  export let openController: Writable<boolean>;
  export let model: CompletionModel | EmbeddingModel | TranscriptionModel;
  export let type: "completionModel" | "embeddingModel" | "transcriptionModel";

  const intric = getIntric();

  // Form state - initialized from model
  let modelIdentifier = "";
  let displayName = "";
  let description = "";
  let maxInputTokensStr = "128000";
  let maxOutputTokensStr = "4096";
  let vision = false;
  let reasoning = false;
  let supportsToolCalling = false;
  let family = "";
  let hosting: "swe" | "eu" | "usa" = "swe";
  let openSource = false;
  let isSubmitting = false;
  let isLoadingDefaults = false;
  let error: string | null = null;

  // Hosting options
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
  ];

  // Initialize form values when dialog opens or model changes
  $: if ($openController && model) {
    initializeForm();
  }

  function initializeForm() {
    modelIdentifier = model.name;
    displayName = "nickname" in model ? (model.nickname || "") : model.name;
    description = model.description || "";
    hosting = model.hosting as "swe" | "eu" | "usa";
    openSource = model.open_source ?? false;

    if ("max_input_tokens" in model && model.max_input_tokens != null) {
      maxInputTokensStr = String(model.max_input_tokens);
    } else if ("token_limit" in model && model.token_limit != null) {
      maxInputTokensStr = String(model.token_limit);
    }
    if ("max_output_tokens" in model && model.max_output_tokens != null) {
      maxOutputTokensStr = String(model.max_output_tokens);
    } else {
      maxOutputTokensStr = "4096";
    }
    if ("vision" in model) {
      vision = model.vision;
    }
    if ("reasoning" in model) {
      reasoning = model.reasoning;
    }
    if ("supports_tool_calling" in model) {
      supportsToolCalling = model.supports_tool_calling;
    }
    if ("family" in model) {
      family = model.family || "";
    }
  }

  async function handleResetToDefaults() {
    if (!modelIdentifier.trim()) return;
    isLoadingDefaults = true;
    try {
      const result = await intric.modelProviders.getModelDefaults(modelIdentifier.trim());
      if (result.found) {
        if (result.max_input_tokens != null) maxInputTokensStr = String(result.max_input_tokens);
        if (result.max_output_tokens != null) maxOutputTokensStr = String(result.max_output_tokens);
        vision = result.supports_vision ?? false;
        reasoning = result.supports_reasoning ?? false;
        supportsToolCalling = result.supports_function_calling ?? false;
        toast.success(m.reset_to_defaults_success());
      } else {
        toast.info(m.reset_to_defaults_not_found({ model: modelIdentifier.trim() }));
      }
    } catch {
      toast.error(m.reset_to_defaults_not_found({ model: modelIdentifier.trim() }));
    } finally {
      isLoadingDefaults = false;
    }
  }

  async function handleSubmit() {
    error = null;

    if (!displayName.trim()) {
      error = m.display_name_required();
      return;
    }

    isSubmitting = true;

    try {
      if (type === "completionModel") {
        const update: TenantCompletionModelUpdate = {
          name: modelIdentifier.trim(),
          display_name: displayName.trim(),
          description: description.trim(),
          hosting,
          open_source: openSource,
          max_input_tokens: parseInt(maxInputTokensStr, 10),
          max_output_tokens: parseInt(maxOutputTokensStr, 10),
          vision,
          reasoning,
          supports_tool_calling: supportsToolCalling
        };
        await intric.tenantModels.updateCompletion({ id: model.id }, update);
      } else if (type === "embeddingModel") {
        const update: TenantEmbeddingModelUpdate = {
          display_name: displayName.trim(),
          description: description.trim(),
          hosting,
          open_source: openSource,
          family: family.trim() || undefined
        };
        await intric.tenantModels.updateEmbedding({ id: model.id }, update);
      } else if (type === "transcriptionModel") {
        const update: TenantTranscriptionModelUpdate = {
          display_name: displayName.trim(),
          description: description.trim(),
          hosting,
          open_source: openSource
        };
        await intric.tenantModels.updateTranscription({ id: model.id }, update);
      }

      // Invalidate to reload data
      await invalidate("admin:model-providers:load");

      // Show success toast
      toast.success(m.model_updated_success());

      // Close dialog
      openController.set(false);
    } catch (e: any) {
      error = e.message || m.failed_to_update_model();
      toast.error(m.failed_to_update_model());
    } finally {
      isSubmitting = false;
    }
  }

  function formatTokenLimit(limit: number): string {
    if (limit >= 1_000_000) return `${(limit / 1_000_000).toFixed(limit % 1_000_000 === 0 ? 0 : 1)}M`;
    if (limit >= 1_000) return `${Math.round(limit / 1_000)}K`;
    return limit.toString();
  }

  function handleCancel() {
    openController.set(false);
    error = null;
  }
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="large" form>
    <Dialog.Title>{m.edit_model()}</Dialog.Title>

    <Dialog.Section>
      <form on:submit|preventDefault={handleSubmit} class="flex flex-col gap-4 p-4">
        {#if error}
          <div class="border-negative-default bg-negative-dimmer text-negative-stronger border-l-2 px-4 py-2 text-sm rounded-r">
            {error}
          </div>
        {/if}

        <!-- Model identifier (editable for completion models, read-only for others) -->
        <div class="flex flex-col gap-2">
          <label for="model-identifier" class="text-sm font-medium text-secondary">{m.model_identifier()}</label>
          {#if type === "completionModel"}
            <Input.Text
              id="model-identifier"
              bind:value={modelIdentifier}
              required
            />
          {:else}
            <div class="flex items-center rounded-lg px-4 py-3 border border-dimmer bg-secondary transition-colors duration-150 hover:border-default">
              <span class="text-sm font-mono text-muted">{model.name}</span>
            </div>
            <p class="text-muted-foreground text-xs mt-1">
              {m.model_identifier_readonly()}
            </p>
          {/if}
        </div>

        <!-- Display name (editable) -->
        <div class="flex flex-col gap-2">
          <label for="display-name" class="text-sm font-medium text-secondary">{m.display_name()}</label>
          <Input.Text
            id="display-name"
            bind:value={displayName}
            placeholder={m.display_name_placeholder_completion()}
            required
          />
          <p class="text-muted-foreground text-xs mt-1">
            {m.display_name_hint()}
          </p>
        </div>

        <!-- Description -->
        <div class="flex flex-col gap-2">
          <label for="description" class="text-sm font-medium text-secondary">{m.description()}</label>
          <textarea
            id="description"
            bind:value={description}
            placeholder={m.model_description_placeholder()}
            rows="3"
            class="rounded-lg border border-stronger bg-primary px-3 py-2 text-sm resize-none shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2 ring-default transition-shadow"
          ></textarea>
        </div>

        <!-- Completion model specific fields -->
        {#if type === "completionModel"}
          <div class="grid grid-cols-2 gap-4">
            <div class="flex flex-col gap-2">
              <label for="max-input-tokens" class="text-sm font-medium text-secondary">{m.max_input_tokens()}</label>
              <Input.Text
                id="max-input-tokens"
                type="number"
                bind:value={maxInputTokensStr}
                min="1024"
                max="10000000"
                required
              />
              <p class="text-muted-foreground text-xs mt-1">
                {m.max_input_tokens_help()}
              </p>
            </div>

            <div class="flex flex-col gap-2">
              <label for="max-output-tokens" class="text-sm font-medium text-secondary">{m.max_output_tokens()}</label>
              <Input.Text
                id="max-output-tokens"
                type="number"
                bind:value={maxOutputTokensStr}
                min="1"
                max="10000000"
                required
              />
              <p class="text-muted-foreground text-xs mt-1">
                {m.max_output_tokens_help()}
              </p>
            </div>
          </div>

          <div class="flex items-center justify-between">
            <p class="text-xs text-muted">
              {m.effective_context({ tokens: formatTokenLimit(Math.max(0, parseInt(maxInputTokensStr, 10) - parseInt(maxOutputTokensStr, 10))) })}
            </p>
            <button
              type="button"
              class="text-xs text-accent-default hover:text-accent-stronger transition-colors underline underline-offset-2 disabled:opacity-50 disabled:cursor-not-allowed flex items-center gap-1"
              disabled={isLoadingDefaults || !modelIdentifier.trim()}
              on:click={handleResetToDefaults}
            >
              {#if isLoadingDefaults}
                <Loader2 class="w-3 h-3 animate-spin" />
              {/if}
              {m.reset_to_defaults()}
            </button>
          </div>

          <div class="flex gap-6">
            <label class="flex items-center gap-2 text-sm cursor-pointer group">
              <input
                type="checkbox"
                bind:checked={vision}
                class="h-4 w-4 rounded border-stronger accent-accent-default cursor-pointer"
              />
              <span class="group-hover:text-primary transition-colors">{m.vision_support()}</span>
            </label>

            <label class="flex items-center gap-2 text-sm cursor-pointer group">
              <input
                type="checkbox"
                bind:checked={reasoning}
                class="h-4 w-4 rounded border-stronger accent-accent-default cursor-pointer"
              />
              <span class="group-hover:text-primary transition-colors">{m.reasoning_support()}</span>
            </label>

            <label class="flex items-center gap-2 text-sm cursor-pointer group">
              <input
                type="checkbox"
                bind:checked={supportsToolCalling}
                class="h-4 w-4 rounded border-stronger accent-accent-default cursor-pointer"
              />
              <span class="group-hover:text-primary transition-colors">{m.tool_calling_support()}</span>
            </label>
          </div>
        {/if}

        <!-- Embedding model specific fields -->
        {#if type === "embeddingModel"}
          <div class="flex flex-col gap-2">
            <label for="family" class="text-sm font-medium text-secondary">{m.model_family()}</label>
            <select
              id="family"
              bind:value={family}
              class="rounded-lg border border-stronger bg-primary px-3 py-2.5 text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2 ring-default transition-shadow cursor-pointer"
            >
              <option value="openai">{m.model_family_openai()}</option>
              <option value="e5">{m.model_family_e5()}</option>
            </select>
            <p class="text-muted-foreground text-xs mt-1">
              {m.model_family_hint()}
            </p>
          </div>
        {/if}

        <!-- Common detail fields -->
        <div class="border-t border-dimmer pt-5 mt-4">
          <h3 class="text-sm font-semibold mb-4 text-secondary">{m.model_details()}</h3>

          <!-- Hosting -->
          <div class="flex flex-col gap-2">
            <label for="hosting" class="text-sm font-medium text-secondary">{m.hosting_region()}</label>
            <select
              id="hosting"
              bind:value={hosting}
              class="rounded-lg border border-stronger bg-primary px-3 py-2.5 text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2 ring-default transition-shadow cursor-pointer"
            >
              {#each hostingOptions as option}
                <option value={option.value}>{option.label}</option>
              {/each}
            </select>
          </div>

          <!-- Open source -->
          <div class="mt-4">
            <label class="flex items-center gap-2 text-sm cursor-pointer group">
              <input
                type="checkbox"
                bind:checked={openSource}
                class="h-4 w-4 rounded border-stronger accent-accent-default cursor-pointer"
              />
              <span class="group-hover:text-primary transition-colors">{m.model_label_open_source()}</span>
            </label>
          </div>
        </div>
      </form>
    </Dialog.Section>

    <Dialog.Controls>
      <Button variant="outlined" on:click={handleCancel}>{m.cancel()}</Button>
      <Button
        variant="primary"
        on:click={handleSubmit}
        disabled={isSubmitting}
        class="min-w-[120px]"
      >
        {#if isSubmitting}
          <Loader2 class="w-4 h-4 mr-2 animate-spin" />
          {m.saving()}
        {:else}
          {m.save()}
        {/if}
      </Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
