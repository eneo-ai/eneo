<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Edit a single existing model. Reuses the same `ModelDraftForm` that the
  AddWizard's Step 3 uses, so cost/description/lookup-defaults stay in one
  place. The only thing this component owns is:
    - converting the API model into the form's draft shape on open
    - building the right Tenant*Update body on submit
    - persisting security_classification + is_org_default through the
      legacy `intric.models.update` endpoint (the tenant routes don't
      cover those two fields).
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
  import { toastError } from "$lib/core/errors";
  import { getIntric } from "$lib/core/Intric";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";

  import ModelDraftForm from "./AddWizard/models/ModelDraftForm.svelte";
  import {
    createEmptyDraft,
    modelToDraft,
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
      output_cost_per_token: tokenCostFromPerMillion(draft.outputCostPerTokenStr)
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
      output_cost_per_token: tokenCostFromPerMillion(draft.outputCostPerTokenStr)
    };
  }

  function buildTranscriptionUpdate(): TenantTranscriptionModelUpdate {
    return {
      display_name: draft.displayName.trim(),
      description: draft.description.trim() || null,
      hosting: draft.hosting,
      open_source: openSource,
      cost_per_minute: parseCost(draft.costPerMinuteStr)
    };
  }

  // Per-minute is stored as-is — no unit conversion needed. The token-cost
  // fields go through `tokenCostFromPerMillion` instead.
  function parseCost(value: string): number | null {
    const trimmed = value.trim();
    if (!trimmed) return null;
    const n = Number(trimmed);
    return Number.isFinite(n) ? n : null;
  }

  async function handleSubmit() {
    error = null;
    if (!draft.displayName.trim()) {
      error = m.display_name_required();
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

      await syncSecurityAndDefault();

      await invalidate("admin:model-providers:load");
      toast.success(m.model_updated_success());
      dialogOpen = false;
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : m.failed_to_update_model();
      toastError(e, m.failed_to_update_model());
    } finally {
      isSubmitting = false;
    }
  }

  // The two cross-cutting fields live on a different endpoint; we only call
  // it when something actually changed, and we branch the call so the
  // discriminated-union typings narrow without a cast.
  async function syncSecurityAndDefault() {
    const classificationChanged =
      (draft.securityClassification?.id ?? null) !== (model.security_classification?.id ?? null);
    const defaultChanged = "is_org_default" in model && isDefault !== model.is_org_default;
    if (!classificationChanged && !defaultChanged) return;

    const update: Record<string, unknown> = {};
    if (classificationChanged) update.security_classification = draft.securityClassification;
    if (defaultChanged) update.is_org_default = isDefault;

    if (type === "completionModel") {
      await intric.models.update({
        completionModel: { id: model.id },
        update
      });
    } else if (type === "embeddingModel") {
      await intric.models.update({
        embeddingModel: { id: model.id },
        update
      });
    } else {
      await intric.models.update({
        transcriptionModel: { id: model.id },
        update
      });
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
