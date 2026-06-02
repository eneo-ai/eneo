<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Edit a single existing model. Reuses the same `ModelDraftForm` that the
  AddWizard's Step 3 uses, so cost/description/lookup-defaults stay in one
  place. The component owns:
    - converting the API model into the form's draft shape on open
    - building the right Tenant*Update body on submit (a single round-trip;
      the legacy intric.models.update fallback for security_classification
      and is_default no longer exists — those fields live on the tenant
      update contract now).
-->

<script lang="ts">
  import { onMount, untrack } from "svelte";
  import type {
    CompletionModel,
    EmbeddingModel,
    TranscriptionModel,
    TenantCompletionModelUpdate,
    TenantEmbeddingModelUpdate,
    TenantTranscriptionModelUpdate
  } from "@intric/intric-js";
  import { invalidate } from "$app/navigation";
  import type { Writable } from "svelte/store";
  import { Loader2 } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { getErrorMessage, toastError } from "$lib/core/errors";
  import { getIntric } from "$lib/core/Intric";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";

  import ModelDraftForm from "./AddWizard/models/ModelDraftForm.svelte";
  import {
    createEmptyDraft,
    findDraftCostOverflow,
    hasValidCompletionTokenBudgets,
    MAX_COST_INPUT,
    modelToDraft,
    rawCostToNumber,
    tokenCostFromPerMillion,
    type ModelDraftState,
    type ModelType
  } from "./AddWizard/models/draft";

  type ModelTypeKey = "completionModel" | "embeddingModel" | "transcriptionModel";

  let {
    openController,
    model,
    type
  }: {
    openController: Writable<boolean>;
    model: CompletionModel | EmbeddingModel | TranscriptionModel;
    type: ModelTypeKey;
  } = $props();

  const intric = getIntric();

  // --- Open-state bridge (Writable<boolean> ↔ runes) --------------------
  let dialogOpen = $state(false);
  onMount(() => openController.subscribe((v) => (dialogOpen = v)));
  $effect(() => {
    openController.set(dialogOpen);
  });

  // --- Draft state ------------------------------------------------------
  const modelType: ModelType = $derived(
    type === "completionModel"
      ? "completion"
      : type === "embeddingModel"
        ? "embedding"
        : "transcription"
  );

  let draft = $state<ModelDraftState>(untrack(() => createEmptyDraft(modelType, "openai")));
  let isDefault = $state(false);
  let openSource = $state(false);
  let isSubmitting = $state(false);
  let error = $state<string | null>(null);

  // Re-seed every time the dialog opens or the underlying record changes.
  // We seed on the falling edge of dialogOpen too so a closed-then-reopened
  // dialog forgets unsaved edits — matches the wizard's behaviour.
  let lastSeededFor: { id: string; open: boolean } | null = null;
  $effect(() => {
    if (!dialogOpen) {
      lastSeededFor = null;
      return;
    }
    if (lastSeededFor?.id === model.id && lastSeededFor.open) return;
    draft = modelToDraft(model, modelType);
    isDefault = "is_org_default" in model ? Boolean(model.is_org_default) : false;
    openSource = model.open_source ?? false;
    error = null;
    lastSeededFor = { id: model.id, open: true };
  });

  // --- Submit -----------------------------------------------------------

  // `is_default` is only edited via the dialog for model types that surface
  // an `is_org_default` field (completion + embedding today). Including it
  // in the payload when the checkbox wasn't rendered would let a stale UI
  // state silently demote a tenant default.
  const hasDefaultToggle = $derived("is_org_default" in model);

  // Send security_classification only when it actually changed — and use
  // explicit null (rather than omission) when the user cleared it, since
  // the backend distinguishes "field omitted" from "field set to null".
  function securityClassificationPatch():
    | { security_classification: { id: string } | null }
    | Record<string, never> {
    const next = draft.securityClassification?.id ?? null;
    const prev = model.security_classification?.id ?? null;
    if (next === prev) return {};
    return { security_classification: next ? { id: next } : null };
  }

  function buildCompletionUpdate(): TenantCompletionModelUpdate {
    return {
      name: draft.name.trim(),
      display_name: draft.displayName.trim(),
      description: draft.description.trim() || null,
      hosting: draft.hosting,
      open_source: openSource,
      max_input_tokens: draft.maxInputTokensStr ? parseInt(draft.maxInputTokensStr, 10) : null,
      max_output_tokens: draft.maxOutputTokensStr ? parseInt(draft.maxOutputTokensStr, 10) : null,
      vision: draft.vision,
      reasoning: draft.reasoning,
      supports_tool_calling: draft.supportsToolCalling,
      input_cost_per_token: tokenCostFromPerMillion(draft.inputCostPerTokenStr),
      output_cost_per_token: tokenCostFromPerMillion(draft.outputCostPerTokenStr),
      ...(hasDefaultToggle ? { is_default: isDefault } : {}),
      ...securityClassificationPatch()
    };
  }

  function buildEmbeddingUpdate(): TenantEmbeddingModelUpdate {
    return {
      display_name: draft.displayName.trim(),
      description: draft.description.trim() || null,
      family: draft.family.trim() || null,
      dimensions: draft.dimensionsStr ? parseInt(draft.dimensionsStr, 10) : null,
      max_input: draft.maxInputStr ? parseInt(draft.maxInputStr, 10) : null,
      hosting: draft.hosting,
      open_source: openSource,
      input_cost_per_token: tokenCostFromPerMillion(draft.inputCostPerTokenStr),
      output_cost_per_token: tokenCostFromPerMillion(draft.outputCostPerTokenStr),
      ...(hasDefaultToggle ? { is_default: isDefault } : {}),
      ...securityClassificationPatch()
    };
  }

  function buildTranscriptionUpdate(): TenantTranscriptionModelUpdate {
    return {
      display_name: draft.displayName.trim(),
      description: draft.description.trim() || null,
      hosting: draft.hosting,
      open_source: openSource,
      cost_per_minute: rawCostToNumber(draft.costPerMinuteStr),
      ...(hasDefaultToggle ? { is_default: isDefault } : {}),
      ...securityClassificationPatch()
    };
  }

  async function handleSubmit() {
    error = null;
    if (!draft.displayName.trim()) {
      error = m.display_name_required();
      return;
    }
    // Mirror the AddWizard guard: completion models cannot persist with
    // null/0 token budgets — the backend rejects them and downstream code
    // would divide by zero on context-window math.
    if (modelType === "completion" && !hasValidCompletionTokenBudgets(draft)) {
      error = m.completion_token_budgets_required();
      return;
    }
    if (findDraftCostOverflow(draft) !== null) {
      error = m.cost_value_too_large({ max: MAX_COST_INPUT.toLocaleString("en-US") });
      return;
    }
    isSubmitting = true;
    try {
      if (type === "completionModel") {
        await intric.tenantModels.updateCompletion({ id: model.id }, buildCompletionUpdate());
      } else if (type === "embeddingModel") {
        await intric.tenantModels.updateEmbedding({ id: model.id }, buildEmbeddingUpdate());
      } else {
        await intric.tenantModels.updateTranscription({ id: model.id }, buildTranscriptionUpdate());
      }

      await invalidate("admin:model-providers:load");
      toast.success(m.model_updated_success());
      dialogOpen = false;
    } catch (e: unknown) {
      error = getErrorMessage(e);
      toastError(e, m.failed_to_update_model());
    } finally {
      isSubmitting = false;
    }
  }

  function handleCancel() {
    dialogOpen = false;
    error = null;
  }
</script>

<Dialog.Root bind:open={dialogOpen}>
  <Dialog.Content class="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-3xl">
    <Dialog.Header class="px-6 pt-6 pb-2">
      <Dialog.Title>{m.edit_model()}</Dialog.Title>
    </Dialog.Header>

    <div class="min-h-0 flex-1 overflow-y-auto px-6 py-4">
      {#if error}
        <div
          class="border-destructive bg-destructive/10 text-destructive mb-4 border-l-2 px-4 py-2 text-sm"
          role="alert"
        >
          {error}
        </div>
      {/if}

      <div class="flex flex-col gap-4">
        <ModelDraftForm
          bind:draft
          {modelType}
          providerType={"provider_type" in model ? (model.provider_type ?? undefined) : undefined}
          showAddAnotherButton={false}
          nameReadOnly={type !== "completionModel"}
        />

        <fieldset class="border-border/40 mt-2 border-t pt-4">
          <legend class="sr-only">{m.model_details()}</legend>
          <div class="flex flex-wrap items-center gap-x-6 gap-y-3">
            <Field.Field orientation="horizontal" class="w-fit">
              <Checkbox id="open-source" bind:checked={openSource} />
              <Field.Label for="open-source">{m.model_label_open_source()}</Field.Label>
            </Field.Field>
            {#if "is_org_default" in model}
              <Field.Field orientation="horizontal" class="w-fit">
                <Checkbox id="is-default" bind:checked={isDefault} />
                <Field.Label for="is-default">{m.default_model()}</Field.Label>
              </Field.Field>
            {/if}
          </div>
        </fieldset>
      </div>
    </div>

    <div class="border-border flex justify-end gap-2 border-t px-6 py-4">
      <Button variant="outline" onclick={handleCancel}>{m.cancel()}</Button>
      <Button onclick={handleSubmit} disabled={isSubmitting}>
        {#if isSubmitting}
          <Loader2 class="animate-spin" aria-hidden="true" />
        {/if}
        {isSubmitting ? m.saving() : m.save()}
      </Button>
    </div>
  </Dialog.Content>
</Dialog.Root>
