<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Edit a single existing model. Reuses the same `ModelDraftForm` that the
  AddWizard's Step 3 uses, so cost/description/lookup-defaults stay in one
  place. The component owns:
    - converting the API model into the form's draft shape on open
    - building the right Tenant*Update body on submit (a single round-trip;
      the legacy eneo.models.update fallback for security_classification
      and is_default no longer exists — those fields live on the tenant
      update contract now).
  A forecast model comes with the installation and has no tenant-model
  contract: its display name and classification go to the forecast model
  endpoint, which also switches it on and off.
-->

<script lang="ts">
  import { onMount, untrack } from "svelte";
  import type {
    CompletionModel,
    EmbeddingModel,
    ForecastModel,
    ImageModel,
    RerankModel,
    TranscriptionModel,
    TenantCompletionModelUpdate,
    TenantEmbeddingModelUpdate,
    TenantImageModelUpdate,
    TenantRerankModelUpdate,
    TenantTranscriptionModelUpdate
  } from "@eneo/eneo-js";
  import { invalidate } from "$app/navigation";
  import type { Writable } from "svelte/store";
  import { LoaderCircle } from "@lucide/svelte";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { getErrorMessage, toastError } from "$lib/core/errors";
  import { getEneo } from "$lib/core/Eneo";
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
    type DraftModelType,
    type ModelDraftState
  } from "./AddWizard/models/draft";

  type ModelTypeKey =
    | "completionModel"
    | "embeddingModel"
    | "transcriptionModel"
    | "imageModel"
    | "rerankModel"
    | "forecastModel";

  let {
    openController,
    model,
    type
  }: {
    openController: Writable<boolean>;
    model:
      | CompletionModel
      | EmbeddingModel
      | TranscriptionModel
      | ImageModel
      | RerankModel
      | ForecastModel;
    type: ModelTypeKey;
  } = $props();

  const eneo = getEneo();

  // --- Open-state bridge (Writable<boolean> ↔ runes) --------------------
  let dialogOpen = $state(false);
  onMount(() => openController.subscribe((v) => (dialogOpen = v)));
  $effect(() => {
    openController.set(dialogOpen);
  });

  // --- Draft state ------------------------------------------------------
  const modelType: DraftModelType = $derived(
    type === "completionModel"
      ? "completion"
      : type === "embeddingModel"
        ? "embedding"
        : type === "imageModel"
          ? "image"
          : type === "rerankModel"
            ? "rerank"
            : type === "forecastModel"
              ? "forecast"
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
  // What the dialog opened with. `model` follows refetches while the dialog is
  // open, so the changed-field checks compare with this, not with `model`:
  // otherwise a value another admin set meanwhile would count as this edit.
  let opened: { displayName: string; classificationId: string | null } = {
    displayName: "",
    classificationId: null
  };
  $effect(() => {
    if (!dialogOpen) {
      lastSeededFor = null;
      return;
    }
    if (lastSeededFor?.id === model.id && lastSeededFor.open) return;
    draft = modelToDraft(model, modelType);
    opened = {
      displayName: draft.displayName.trim(),
      classificationId: model.security_classification?.id ?? null
    };
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

  // Send security_classification only when the admin changed it in this
  // dialog — and use explicit null (rather than omission) when the user
  // cleared it, since the backend distinguishes "field omitted" from "field
  // set to null".
  function securityClassificationPatch():
    { security_classification: { id: string } | null } | Record<string, never> {
    const next = draft.securityClassification?.id ?? null;
    if (next === opened.classificationId) return {};
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

  function buildImageUpdate(): TenantImageModelUpdate {
    return {
      display_name: draft.displayName.trim(),
      description: draft.description.trim() || null,
      hosting: draft.hosting,
      open_source: openSource,
      cost_per_image: rawCostToNumber(draft.costPerImageStr),
      default_size: draft.defaultSize,
      default_quality: draft.defaultQuality,
      ...(hasDefaultToggle ? { is_default: isDefault } : {}),
      ...securityClassificationPatch()
    };
  }

  function buildRerankUpdate(): TenantRerankModelUpdate {
    return {
      display_name: draft.displayName.trim(),
      description: draft.description.trim() || null,
      hosting: draft.hosting,
      open_source: openSource,
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
        await eneo.tenantModels.updateCompletion({ id: model.id }, buildCompletionUpdate());
      } else if (type === "embeddingModel") {
        await eneo.tenantModels.updateEmbedding({ id: model.id }, buildEmbeddingUpdate());
      } else if (type === "imageModel") {
        await eneo.tenantModels.updateImage({ id: model.id }, buildImageUpdate());
      } else if (type === "rerankModel") {
        await eneo.tenantModels.updateRerank({ id: model.id }, buildRerankUpdate());
      } else if (type === "forecastModel") {
        await eneo.models.update({
          forecastModel: { id: model.id },
          // Only the fields the admin changed: an omitted field keeps its value.
          update: {
            ...(draft.displayName.trim() !== opened.displayName
              ? { display_name: draft.displayName.trim() }
              : {}),
            ...securityClassificationPatch()
          }
        });
      } else {
        await eneo.tenantModels.updateTranscription({ id: model.id }, buildTranscriptionUpdate());
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

        {#if modelType !== "forecast"}
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
        {/if}
      </div>
    </div>

    <div class="border-border flex justify-end gap-2 border-t px-6 py-4">
      <Button variant="outline" onclick={handleCancel}>{m.cancel()}</Button>
      <Button onclick={handleSubmit} disabled={isSubmitting}>
        {#if isSubmitting}
          <LoaderCircle class="animate-spin" aria-hidden="true" />
        {/if}
        {isSubmitting ? m.saving() : m.save()}
      </Button>
    </div>
  </Dialog.Content>
</Dialog.Root>
