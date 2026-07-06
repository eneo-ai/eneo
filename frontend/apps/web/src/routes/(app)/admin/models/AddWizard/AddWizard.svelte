<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Three-step wizard for adding a model provider and one or more models.

  Responsibilities of this orchestrator:
    1. Own the wizard data + current step.
    2. Mount the shadcn Dialog and the step indicator.
    3. Route between Step 1 (provider), Step 2 (credentials) and Step 3 (models).
    4. Validate models against the provider before creating, and offer a
       "create anyway" escape hatch when validation produces warnings.

  What is intentionally NOT here:
    - Field-level rendering — lives in the step children.
    - Provider/field metadata — comes from `modelProviderCapabilities`.
    - Hosting options — come from `lib/features/ai-models/hosting`.
-->

<script lang="ts">
  import { onMount } from "svelte";
  import { fly, fade } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { invalidate } from "$app/navigation";
  import type { Writable } from "svelte/store";
  import type { ModelProviderPublic } from "@eneo/eneo-js";
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { toast } from "$lib/components/toast";
  import { getErrorMessage, toastError } from "$lib/core/errors";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Loader2, AlertTriangle } from "lucide-svelte";

  import StepProvider from "./StepProvider.svelte";
  import StepCredentials from "./StepCredentials.svelte";
  import StepModels from "./StepModels.svelte";
  import Stepper, { type Step } from "./Stepper.svelte";
  import {
    getModelProviderCapabilities,
    type ModelProviderCapabilities
  } from "../modelProviderCapabilities";
  import {
    createEmptyWizardData,
    type WizardData,
    type WizardStepId,
    type WizardModelDraft
  } from "./wizardState";
  import { isCostValueOverflow, MAX_COST_INPUT } from "./models/draft";

  type ModelType = "completion" | "embedding" | "transcription";

  let {
    openController,
    providers = [],
    favoriteProviders = [],
    /** Pre-selected provider when entering from a "Add Model" button. */
    preSelectedProviderId = null,
    modelType = "completion"
  }: {
    openController: Writable<boolean>;
    providers?: ModelProviderPublic[];
    favoriteProviders?: string[];
    preSelectedProviderId?: string | null;
    modelType?: ModelType;
  } = $props();

  const eneo = getEneo();

  // --- Open state bridging ------------------------------------------------
  // The host page passes a `Writable<boolean>` (legacy contract). We bridge
  // that to a runes-friendly local boolean so shadcn Dialog's `bind:open`
  // works, then mirror writes back to the store. The two-way sync is
  // self-stabilising: the subscribe callback updates the local state, the
  // effect writes back the same value, and Svelte's $state short-circuits
  // when the value doesn't change, so no infinite loop.

  let dialogOpen = $state(false);

  onMount(() => {
    const unsubscribe = openController.subscribe((value) => {
      dialogOpen = value;
    });
    return unsubscribe;
  });

  $effect(() => {
    openController.set(dialogOpen);
  });

  // --- Capabilities -------------------------------------------------------
  // Lazy load on first open. The capabilities module owns the global cache,
  // so subsequent opens are free.

  let capabilities = $state<ModelProviderCapabilities | null>(null);
  let capabilitiesLoading = $state(false);

  async function ensureCapabilities() {
    if (capabilities || capabilitiesLoading) return;
    capabilitiesLoading = true;
    try {
      capabilities = await getModelProviderCapabilities(eneo);
    } catch {
      // Steps fall back gracefully via `resolveProviderFields(null, ...)`.
    } finally {
      capabilitiesLoading = false;
    }
  }

  // --- Wizard data --------------------------------------------------------

  let wizardData = $state<WizardData>(createEmptyWizardData());
  let currentStep = $state<WizardStepId>("provider");
  let stepDirection = $state<"forward" | "backward">("forward");

  // Pending model — kept here (not bound from child) so we have a single
  // source of truth for the unsubmitted form. The form publishes its draft
  // upward via `onDraftChange` whenever it is "complete enough" to save.
  let pendingDraft = $state<WizardModelDraft | null>(null);

  // --- Open transitions --------------------------------------------------
  // Initialise once per open. We previously did this in a `$:` block which
  // would fire on every reactive change and could bounce the user back to
  // step 3 after they navigated away. An $effect that depends on dialogOpen
  // (and not the data we mutate) avoids that loop.

  let didInitialiseForThisOpen = false;
  $effect(() => {
    if (dialogOpen && !didInitialiseForThisOpen) {
      didInitialiseForThisOpen = true;
      void ensureCapabilities();
      resetWizardForOpen();
    } else if (!dialogOpen && didInitialiseForThisOpen) {
      didInitialiseForThisOpen = false;
    }
  });

  function resetWizardForOpen() {
    wizardData = createEmptyWizardData();
    pendingDraft = null;
    error = null;
    pendingValidationWarnings = [];
    pendingModelsToCreate = [];
    isSubmitting = false;
    isValidating = false;
    stepDirection = "forward";

    if (preSelectedProviderId) {
      const matched = providers.find((p) => p.id === preSelectedProviderId);
      wizardData.selectedProviderId = preSelectedProviderId;
      wizardData.isCreatingNewProvider = false;
      wizardData.selectedProviderType = matched?.provider_type ?? "openai";
      currentStep = "models";
    } else {
      currentStep = "provider";
    }
  }

  // --- Step navigation ---------------------------------------------------

  const STEP_ORDER: WizardStepId[] = ["provider", "credentials", "models"];

  const steps: Step[] = $derived([
    { id: "provider", label: m.wizard_step_provider() },
    { id: "credentials", label: m.wizard_step_credentials() },
    {
      id: "models",
      label: m.wizard_step_models(),
      canJumpTo: !wizardData.isCreatingNewProvider && !!wizardData.selectedProviderId
    }
  ]);

  function jumpToStep(id: string) {
    const next = id as WizardStepId;
    stepDirection =
      STEP_ORDER.indexOf(next) > STEP_ORDER.indexOf(currentStep) ? "forward" : "backward";
    currentStep = next;
  }

  function previousStep() {
    stepDirection = "backward";
    if (currentStep === "credentials") {
      currentStep = "provider";
    } else if (currentStep === "models") {
      // Skip the credentials step on the way back when the user picked an
      // existing provider — we never visited it on the way forward.
      currentStep = wizardData.isCreatingNewProvider ? "credentials" : "provider";
    }
  }

  // --- Step events ------------------------------------------------------

  function handleProviderSelected(detail: {
    providerId: string | null;
    isNew: boolean;
    providerType: string;
  }) {
    wizardData.selectedProviderId = detail.providerId;
    wizardData.isCreatingNewProvider = detail.isNew;
    wizardData.selectedProviderType = detail.providerType;
    stepDirection = "forward";
    currentStep = detail.isNew ? "credentials" : "models";
  }

  function handleCredentialsCompleted(detail: { providerId: string }) {
    wizardData.selectedProviderId = detail.providerId;
    wizardData.isCreatingNewProvider = false;
    stepDirection = "forward";
    currentStep = "models";
  }

  // --- Model creation ---------------------------------------------------

  let isSubmitting = $state(false);
  let isValidating = $state(false);
  let error = $state<string | null>(null);

  let pendingValidationWarnings = $state<string[]>([]);
  let pendingModelsToCreate = $state<WizardModelDraft[]>([]);

  // Step 3 publishes whether finishing is allowed. This includes both
  // "models already added" and "form is complete enough to flush on finish".
  let canFinish = $state(false);

  async function finishWizard(skip: boolean) {
    if (skip) {
      await reloadAndClose();
      return;
    }

    error = null;
    isSubmitting = true;

    try {
      const providerId = wizardData.selectedProviderId;
      if (!providerId) throw new Error(m.no_provider_selected());

      const modelsToCreate: WizardModelDraft[] = [...wizardData.models];
      if (pendingDraft) modelsToCreate.push(pendingDraft);

      if (modelsToCreate.length === 0) throw new Error(m.add_at_least_one_model());

      for (const model of modelsToCreate) {
        if (
          isCostValueOverflow(model.inputCostPerToken) ||
          isCostValueOverflow(model.outputCostPerToken) ||
          isCostValueOverflow(model.costPerMinute, true)
        ) {
          throw new Error(m.cost_value_too_large({ max: MAX_COST_INPUT.toLocaleString("en-US") }));
        }
      }

      isValidating = true;
      const warnings = await collectValidationWarnings(modelsToCreate, providerId);
      isValidating = false;

      if (warnings.length > 0) {
        pendingValidationWarnings = warnings;
        pendingModelsToCreate = modelsToCreate;
        isSubmitting = false;
        return;
      }

      await createModels(modelsToCreate, providerId);
    } catch (e: unknown) {
      error = getErrorMessage(e);
      toastError(e, m.failed_to_create_model());
    } finally {
      isSubmitting = false;
      isValidating = false;
    }
  }

  async function collectValidationWarnings(
    models: WizardModelDraft[],
    providerId: string
  ): Promise<string[]> {
    const warnings: string[] = [];
    for (const model of models) {
      try {
        const result = await eneo.modelProviders.validateModel(
          { id: providerId },
          { model_name: model.name, model_type: modelType }
        );
        if (!result.success && result.error) {
          warnings.push(`${model.name}: ${result.error}`);
        }
      } catch {
        // Validation endpoint failure is non-fatal — we'll let the create
        // call surface a real error if there is one.
      }
    }
    return warnings;
  }

  async function createAnyway() {
    error = null;
    isSubmitting = true;
    const models = pendingModelsToCreate;
    const providerId = wizardData.selectedProviderId;
    pendingValidationWarnings = [];
    pendingModelsToCreate = [];

    try {
      if (!providerId) throw new Error(m.no_provider_selected());
      await createModels(models, providerId);
    } catch (e: unknown) {
      error = getErrorMessage(e);
      toastError(e, m.failed_to_create_model());
    } finally {
      isSubmitting = false;
    }
  }

  function dismissValidationWarning() {
    pendingValidationWarnings = [];
    pendingModelsToCreate = [];
  }

  async function createModels(models: WizardModelDraft[], providerId: string) {
    // Track per-model outcomes: a single throw mid-loop would leave the
    // already-created rows queued in wizardData.models, so the user could
    // not retry without hitting duplicate-name errors on the backend.
    const succeeded: WizardModelDraft[] = [];
    const failures: { model: WizardModelDraft; error: unknown }[] = [];

    for (const model of models) {
      try {
        await createOneModel(model, providerId);
        succeeded.push(model);
      } catch (err) {
        failures.push({ model, error: err });
      }
    }

    // Drop the succeeded entries from the wizard list so a retry only
    // resubmits what actually failed. wizardData.models keeps reference
    // identity with the source array, so filter on identity.
    // pendingDraft is pushed into modelsToCreate by reference in finishWizard,
    // so if it succeeded it must be cleared too — otherwise the next finish
    // resubmits it and the backend rejects on duplicate name.
    if (succeeded.length > 0) {
      wizardData.models = wizardData.models.filter((m) => !succeeded.includes(m));
      if (pendingDraft && succeeded.includes(pendingDraft)) {
        pendingDraft = null;
      }
    }

    if (failures.length === 0) {
      toast.success(
        models.length === 1
          ? m.model_created_success()
          : m.models_created_success({ count: models.length })
      );
      await reloadAndClose();
      return;
    }

    if (succeeded.length === 0) {
      // All failed — propagate the first error so the dialog's catch
      // sets the error banner and the dialog stays open.
      throw failures[0].error;
    }

    // Partial: surface a warning that names the failing models and
    // leave the dialog open with only the failed rows still queued.
    const failedNames = failures.map((f) => f.model.name).join(", ");
    toast.warning(
      m.models_partially_created({
        succeeded: succeeded.length,
        total: models.length,
        failed: failedNames
      })
    );
  }

  async function createOneModel(
    model: WizardModelDraft,
    providerId: string
  ): Promise<{ id: string } | undefined> {
    if (modelType === "completion") {
      return eneo.tenantModels.createCompletion({
        provider_id: providerId,
        name: model.name,
        display_name: model.displayName,
        family: model.family ?? "openai",
        max_input_tokens: model.maxInputTokens,
        max_output_tokens: model.maxOutputTokens,
        vision: model.vision ?? false,
        reasoning: model.reasoning ?? false,
        supports_tool_calling: model.supportsToolCalling ?? false,
        hosting: model.hosting ?? "swe",
        is_active: true,
        description: model.description ?? null,
        input_cost_per_token: model.inputCostPerToken ?? null,
        output_cost_per_token: model.outputCostPerToken ?? null,
        security_classification: model.securityClassification
          ? { id: model.securityClassification.id }
          : null
      });
    }
    if (modelType === "embedding") {
      return eneo.tenantModels.createEmbedding({
        provider_id: providerId,
        name: model.name,
        display_name: model.displayName,
        family: model.family ?? "openai",
        dimensions: model.dimensions ?? undefined,
        max_input: model.maxInput ?? undefined,
        hosting: model.hosting ?? "swe",
        is_active: true,
        description: model.description ?? null,
        input_cost_per_token: model.inputCostPerToken ?? null,
        output_cost_per_token: model.outputCostPerToken ?? null,
        security_classification: model.securityClassification
          ? { id: model.securityClassification.id }
          : null
      });
    }
    return eneo.tenantModels.createTranscription({
      provider_id: providerId,
      name: model.name,
      display_name: model.displayName,
      family: model.family ?? "openai",
      hosting: model.hosting ?? "swe",
      is_active: true,
      description: model.description ?? null,
      cost_per_minute: model.costPerMinute ?? null,
      security_classification: model.securityClassification
        ? { id: model.securityClassification.id }
        : null
    });
  }

  async function reloadAndClose() {
    await Promise.all([invalidate("admin:model-providers:load"), invalidate("admin:models:load")]);
    dialogOpen = false;
  }

  // --- Transitions ------------------------------------------------------

  const transitionDuration = 250;
  const flyX = $derived(stepDirection === "forward" ? 24 : -24);
</script>

<Dialog.Root bind:open={dialogOpen}>
  <Dialog.Content class="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-3xl" showCloseButton={false}>
    <Dialog.Header
      class="from-surface-dimmer/50 gap-6 bg-gradient-to-b to-transparent px-6 pt-6 pb-4"
    >
      <Dialog.Title>{m.add_provider_and_models()}</Dialog.Title>
      <Stepper
        {steps}
        currentId={currentStep}
        onJump={jumpToStep}
        aria-label={m.add_provider_and_models()}
      />
    </Dialog.Header>

    <div class="min-h-0 flex-1 overflow-y-auto px-8 py-6">
      {#if error}
        <div
          class="border-destructive bg-destructive/10 text-destructive mb-4 border-l-2 px-4 py-2 text-sm"
          role="alert"
        >
          {error}
        </div>
      {/if}

      {#if pendingValidationWarnings.length > 0}
        <div
          class="border-warning-default/30 bg-warning-dimmer/50 flex items-start gap-3 rounded-lg border p-4"
          role="alert"
        >
          <AlertTriangle
            class="text-warning-default mt-0.5 h-5 w-5 flex-shrink-0"
            aria-hidden="true"
          />
          <div class="flex-1">
            <p class="text-warning-stronger text-sm font-medium">
              {m.model_validation_warning_title()}
            </p>
            <ul class="mt-2 space-y-1">
              {#each pendingValidationWarnings as warning, i (i)}
                <li class="text-warning-default text-sm">{warning}</li>
              {/each}
            </ul>
          </div>
        </div>
      {:else}
        <div
          class="grid min-h-[380px] items-start overflow-hidden"
          style="grid-template: 1fr / 1fr;"
        >
          {#key currentStep}
            <div
              in:fly={{
                x: flyX,
                duration: transitionDuration,
                delay: transitionDuration * 0.4,
                easing: cubicOut,
                opacity: 0
              }}
              out:fade={{ duration: transitionDuration * 0.35 }}
              class="w-full"
              style="grid-area: 1 / 1;"
            >
              {#if currentStep === "provider"}
                <StepProvider
                  {providers}
                  {favoriteProviders}
                  {capabilities}
                  selectedProviderId={wizardData.selectedProviderId}
                  onSelect={handleProviderSelected}
                />
              {:else if currentStep === "credentials"}
                <StepCredentials
                  providerType={wizardData.selectedProviderType}
                  {capabilities}
                  onComplete={handleCredentialsCompleted}
                  onBack={previousStep}
                />
              {:else if currentStep === "models"}
                <StepModels
                  {modelType}
                  {capabilities}
                  providerType={wizardData.selectedProviderType}
                  providerId={wizardData.selectedProviderId}
                  bind:models={wizardData.models}
                  bind:canFinish
                  onDraftChange={(draft) => (pendingDraft = draft)}
                  onBack={previousStep}
                  onSkip={() => finishWizard(true)}
                />
              {/if}
            </div>
          {/key}
        </div>
      {/if}
    </div>

    <div class="border-border flex justify-end gap-2 border-t px-6 py-4">
      {#if pendingValidationWarnings.length > 0}
        <Button variant="outline" onclick={dismissValidationWarning}>{m.back()}</Button>
        <Button onclick={createAnyway} disabled={isSubmitting}>
          {#if isSubmitting}
            <Loader2 class="animate-spin" aria-hidden="true" />
          {/if}
          {isSubmitting ? m.creating() : m.create_anyway()}
        </Button>
      {:else}
        <Button variant="outline" onclick={() => reloadAndClose()}>{m.cancel()}</Button>
        {#if currentStep === "models"}
          <Button
            onclick={() => finishWizard(false)}
            disabled={isSubmitting || isValidating || !canFinish}
          >
            {#if isSubmitting || isValidating}
              <Loader2 class="animate-spin" aria-hidden="true" />
            {/if}
            {isValidating ? m.validating_models() : isSubmitting ? m.creating() : m.finish()}
          </Button>
        {/if}
      {/if}
    </div>
  </Dialog.Content>
</Dialog.Root>
