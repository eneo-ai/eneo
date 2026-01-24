<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { Button, Dialog } from "@intric/ui";
  import { writable, type Writable } from "svelte/store";
  import { fly, fade } from "svelte/transition";
  import { cubicOut } from "svelte/easing";
  import { invalidate } from "$app/navigation";
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { Check } from "lucide-svelte";
  import StepProvider from "./StepProvider.svelte";
  import StepCredentials from "./StepCredentials.svelte";
  import StepModels from "./StepModels.svelte";
  import type { ModelProviderPublic } from "@intric/intric-js";

  export let openController: Writable<boolean>;
  export let providers: ModelProviderPublic[] = [];
  /** Pre-selected provider ID when opening wizard from a provider's "Add Model" button */
  export let preSelectedProviderId: string | null = null;
  /** Model type to add (for when starting from "Add Model" on a specific table) */
  export let modelType: "completion" | "embedding" | "transcription" = "completion";

  const intric = getIntric();

  // Wizard state
  type WizardStep = 1 | 2 | 3;
  const currentStep = writable<WizardStep>(1);

  // Step direction for transitions
  let stepDirection: "forward" | "backward" = "forward";

  // Wizard data collected across steps
  interface WizardData {
    // Step 1: Provider selection
    selectedProviderId: string | null;
    isCreatingNewProvider: boolean;
    selectedProviderType: string;

    // Step 2: New provider credentials
    providerName: string;
    apiKey: string;
    endpoint: string;
    apiVersion: string;
    deploymentName: string;

    // Step 3: Model(s) to add
    models: Array<{
      name: string;
      displayName: string;
      tokenLimit?: number;
      vision?: boolean;
      reasoning?: boolean;
      family?: string;
      dimensions?: number;
      maxInput?: number;
    }>;
  }

  const wizardData = writable<WizardData>({
    selectedProviderId: preSelectedProviderId,
    isCreatingNewProvider: false,
    selectedProviderType: "openai",
    providerName: "",
    apiKey: "",
    endpoint: "",
    apiVersion: "",
    deploymentName: "",
    models: []
  });

  // Determine starting step based on context
  $: {
    if (preSelectedProviderId && $openController) {
      // Coming from "Add Model" button on a provider - skip to step 3
      $wizardData.selectedProviderId = preSelectedProviderId;
      $wizardData.isCreatingNewProvider = false;
      $currentStep = 3;
    }
  }

  // Step labels for progress indicator
  const stepLabels = [
    { step: 1, labelKey: "wizard_step_provider" },
    { step: 2, labelKey: "wizard_step_credentials" },
    { step: 3, labelKey: "wizard_step_models" }
  ] as const;

  function getStepLabel(labelKey: string): string {
    switch (labelKey) {
      case "wizard_step_provider": return m.wizard_step_provider();
      case "wizard_step_credentials": return m.wizard_step_credentials();
      case "wizard_step_models": return m.wizard_step_models();
      default: return "";
    }
  }

  // Navigation
  function goToStep(step: WizardStep) {
    if (step < $currentStep) {
      stepDirection = "backward";
    } else {
      stepDirection = "forward";
    }
    $currentStep = step;
  }

  function nextStep() {
    stepDirection = "forward";
    if ($currentStep < 3) {
      $currentStep = ($currentStep + 1) as WizardStep;
    }
  }

  function previousStep() {
    stepDirection = "backward";
    if ($currentStep === 3 && !$wizardData.isCreatingNewProvider) {
      // Skip credentials step when going back if using existing provider
      $currentStep = 1;
    } else if ($currentStep > 1) {
      $currentStep = ($currentStep - 1) as WizardStep;
    }
  }

  // Skip credentials step if using existing provider
  function handleProviderSelected(event: CustomEvent<{ providerId: string | null; isNew: boolean; providerType: string }>) {
    const { providerId, isNew, providerType } = event.detail;
    $wizardData.selectedProviderId = providerId;
    $wizardData.isCreatingNewProvider = isNew;
    $wizardData.selectedProviderType = providerType;

    if (isNew) {
      nextStep(); // Go to credentials
    } else {
      // Skip to models step
      stepDirection = "forward";
      $currentStep = 3;
    }
  }

  // Handle credentials completed
  async function handleCredentialsCompleted(event: CustomEvent<{ providerId: string }>) {
    $wizardData.selectedProviderId = event.detail.providerId;
    $wizardData.isCreatingNewProvider = false;
    nextStep();
  }

  // Handle wizard completion
  let isSubmitting = false;
  let error: string | null = null;

  async function handleComplete(event: CustomEvent<{ skip: boolean }>) {
    if (event.detail.skip) {
      // User chose to skip adding models - just close
      await invalidate("admin:model-providers:load");
      await invalidate("admin:models:load");
      closeWizard();
      return;
    }

    error = null;
    isSubmitting = true;

    try {
      const providerId = $wizardData.selectedProviderId;
      if (!providerId) {
        throw new Error(m.no_provider_selected());
      }

      // Create models based on type
      for (const model of $wizardData.models) {
        if (modelType === "completion") {
          await intric.tenantModels.createCompletion({
            provider_id: providerId,
            name: model.name,
            display_name: model.displayName,
            token_limit: model.tokenLimit ?? 128000,
            vision: model.vision ?? false,
            reasoning: model.reasoning ?? false,
            is_active: true
          });
        } else if (modelType === "embedding") {
          await intric.tenantModels.createEmbedding({
            provider_id: providerId,
            name: model.name,
            display_name: model.displayName,
            family: model.family ?? "openai",
            dimensions: model.dimensions ?? undefined,
            max_input: model.maxInput ?? undefined,
            is_active: true
          });
        } else if (modelType === "transcription") {
          await intric.tenantModels.createTranscription({
            provider_id: providerId,
            name: model.name,
            display_name: model.displayName,
            is_active: true
          });
        }
      }

      await invalidate("admin:model-providers:load");
      await invalidate("admin:models:load");
      closeWizard();
    } catch (e: any) {
      error = e.message || m.failed_to_create_model();
    } finally {
      isSubmitting = false;
    }
  }

  function closeWizard() {
    $openController = false;
    // Reset state
    $currentStep = 1;
    stepDirection = "forward";
    $wizardData = {
      selectedProviderId: null,
      isCreatingNewProvider: false,
      selectedProviderType: "openai",
      providerName: "",
      apiKey: "",
      endpoint: "",
      apiVersion: "",
      deploymentName: "",
      models: []
    };
    error = null;
  }

  function handleCancel() {
    closeWizard();
  }

  // Transition config - smooth crossfade with subtle slide
  const transitionDuration = 250;
  $: flyX = stepDirection === "forward" ? 24 : -24;
</script>

<Dialog.Root {openController}>
  <Dialog.Content width="large" form>
    <!-- Progress Header with subtle gradient -->
    <Dialog.Title class="!pb-0 bg-gradient-to-b from-surface-dimmer/50 to-transparent">
      <div class="flex flex-col gap-6">
        <span>{m.add_provider_and_models()}</span>

        <!-- Step Indicator - Refined text-based design -->
        <nav class="flex items-center" aria-label="Wizard steps">
          {#each stepLabels as { step, labelKey }, i}
            {@const isActive = step === $currentStep}
            {@const isCompleted = step < $currentStep}
            {@const isClickable = step < $currentStep || (step === 3 && !$wizardData.isCreatingNewProvider && $wizardData.selectedProviderId)}

            <!-- Step Label -->
            <button
              type="button"
              class="relative flex items-center gap-2 px-1 py-2 text-sm transition-all duration-150
                {isActive
                  ? 'text-primary font-medium'
                  : isCompleted
                    ? 'text-positive-stronger cursor-pointer hover:text-positive-default'
                    : 'text-muted cursor-default tracking-wide'}"
              disabled={!isClickable}
              on:click={() => isClickable && goToStep(step)}
              aria-current={isActive ? 'step' : undefined}
            >
              {#if isCompleted}
                <Check class="h-4 w-4 text-positive-default" />
              {/if}
              <span>{getStepLabel(labelKey)}</span>

              <!-- Active underline indicator -->
              {#if isActive}
                <span class="absolute bottom-0 left-1 right-1 h-0.5 bg-accent-default rounded-full"></span>
              {/if}
            </button>

            <!-- Connector Line -->
            {#if i < stepLabels.length - 1}
              <div class="mx-3 h-px w-8 transition-colors duration-150
                {step < $currentStep ? 'bg-positive-default' : 'bg-border-dimmer'}">
              </div>
            {/if}
          {/each}
        </nav>
      </div>
    </Dialog.Title>

    <Dialog.Section class="!px-8">
      <div class="relative py-6">
        {#if error}
          <div class="border-error bg-error-dimmer text-error-stronger mb-4 border-l-2 px-4 py-2 text-sm">
            {error}
          </div>
        {/if}

        <!-- Step Content - Grid overlay technique for smooth crossfade without jumping -->
        <div class="grid min-h-[380px] items-start overflow-hidden" style="grid-template: 1fr / 1fr;">
          {#key $currentStep}
            <div
              in:fly={{ x: flyX, duration: transitionDuration, delay: transitionDuration * 0.4, easing: cubicOut, opacity: 0 }}
              out:fade={{ duration: transitionDuration * 0.35 }}
              class="w-full"
              style="grid-area: 1 / 1;"
            >
            {#if $currentStep === 1}
              <StepProvider
                {providers}
                selectedProviderId={$wizardData.selectedProviderId}
                on:select={handleProviderSelected}
              />
            {:else if $currentStep === 2}
              <StepCredentials
                providerType={$wizardData.selectedProviderType}
                bind:providerName={$wizardData.providerName}
                bind:apiKey={$wizardData.apiKey}
                bind:endpoint={$wizardData.endpoint}
                bind:apiVersion={$wizardData.apiVersion}
                bind:deploymentName={$wizardData.deploymentName}
                on:complete={handleCredentialsCompleted}
                on:back={previousStep}
              />
            {:else if $currentStep === 3}
              <StepModels
                {modelType}
                providerType={$wizardData.selectedProviderType}
                providerId={$wizardData.selectedProviderId}
                bind:models={$wizardData.models}
                on:complete={handleComplete}
                on:back={previousStep}
              />
            {/if}
          </div>
        {/key}
      </div>
    </Dialog.Section>

    <!-- Footer with visual separation -->
    <Dialog.Controls class="border-t border-dimmer pt-4">
      <Button variant="outlined" on:click={handleCancel}>{m.cancel()}</Button>

      {#if $currentStep === 3}
        <Button
          variant="primary"
          on:click={() => handleComplete(new CustomEvent("complete", { detail: { skip: false } }))}
          disabled={isSubmitting || $wizardData.models.length === 0}
        >
          {isSubmitting ? m.creating() : m.finish()}
        </Button>
      {/if}
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
