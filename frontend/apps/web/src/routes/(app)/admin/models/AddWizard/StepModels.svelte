<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Step 3 — add one or more models to the selected provider.

  This file orchestrates three concerns:
    - Source the suggestions list (live first, static fallback) — see loadModels.ts
    - Edit the in-progress draft — see ModelDraftForm
    - Show what's been queued — see ModelDraftList
-->

<script lang="ts">
  import { untrack } from "svelte";
  import { ArrowLeft, TriangleAlert } from "lucide-svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getEneo } from "$lib/core/Eneo";

  import {
    formatProviderLabel,
    type ModelProviderCapabilities
  } from "../modelProviderCapabilities";
  import type { WizardModelDraft } from "./wizardState";
  import {
    type ModelDraftState,
    type ModelInfo,
    type ModelType,
    applyCatalogModelToDraft,
    createEmptyDraft,
    draftToWizardModel,
    findDraftCostOverflow,
    isDraftComplete,
    MAX_COST_INPUT
  } from "./models/draft";
  import { toast } from "$lib/components/toast";
  import {
    isSelfHostedProvider,
    loadLiveModels,
    providerSupportsMode,
    staticCatalog
  } from "./models/loadModels";

  import ModelSuggestions from "./models/ModelSuggestions.svelte";
  import ModelDraftForm from "./models/ModelDraftForm.svelte";
  import ModelDraftList from "./models/ModelDraftList.svelte";

  let {
    modelType = "completion",
    providerType,
    providerId,
    capabilities = null,
    models = $bindable([]),
    canFinish = $bindable(false),
    onDraftChange,
    onBack,
    onSkip
  }: {
    modelType?: ModelType;
    providerType: string;
    providerId: string | null;
    capabilities?: ModelProviderCapabilities | null;
    models?: WizardModelDraft[];
    canFinish?: boolean;
    onDraftChange: (draft: WizardModelDraft | null) => void;
    onBack: () => void;
    onSkip: () => void;
  } = $props();

  const eneo = getEneo();

  // --- Draft state -------------------------------------------------------

  // Seed once from the props. The wizard rekeys steps when modelType or
  // providerType changes, so we don't need a derived/effect here.
  let draft = $state<ModelDraftState>(untrack(() => createEmptyDraft(modelType, providerType)));

  const draftComplete = $derived(isDraftComplete(draft, modelType));

  // Publish a snapshot of the draft to the parent so it can flush an
  // un-added but valid form when the user clicks "Finish". Replaces the old
  // bind:this hack.
  $effect(() => {
    onDraftChange(draftComplete ? draftToWizardModel(draft) : null);
  });

  $effect(() => {
    canFinish = models.length > 0 || draftComplete;
  });

  // --- Suggestions -------------------------------------------------------

  // Live results override the static catalog if present. We track the
  // (providerId, mode) tuple so switching tabs or providers re-fetches once.
  let liveModels = $state<ModelInfo[]>([]);
  let liveModelsError = $state<string | null>(null);
  let liveLoadedFor = $state<{ providerId: string; modelType: ModelType } | null>(null);

  $effect(() => {
    if (!providerId) return;
    if (
      liveLoadedFor &&
      liveLoadedFor.providerId === providerId &&
      liveLoadedFor.modelType === modelType
    ) {
      return;
    }
    const requested = { providerId, modelType };
    liveLoadedFor = requested;
    liveModels = [];
    liveModelsError = null;
    void loadLiveModels(eneo, providerId, modelType).then((result) => {
      // Drop stale responses if the user has since switched provider/mode.
      if (
        liveLoadedFor?.providerId !== requested.providerId ||
        liveLoadedFor?.modelType !== requested.modelType
      ) {
        return;
      }
      liveModels = result.models;
      liveModelsError = result.error;
    });
  });

  const allModels = $derived(
    liveModels.length > 0 ? liveModels : staticCatalog(capabilities, providerType, modelType)
  );

  const supportStatus = $derived(providerSupportsMode(capabilities, providerType, modelType));
  const selfHosted = $derived(isSelfHostedProvider(capabilities, providerType));

  // Raw `providerType` ("openai", "hosted_vllm") and `modelType`
  // ("completion") are machine identifiers — surface them via the
  // existing formatter + localised type labels so admins don't see
  // "hosted_vllm" or "transcription" in plain text alerts.
  const providerLabel = $derived(formatProviderLabel(providerType));
  const modelTypeLabel = $derived(
    modelType === "completion"
      ? m.model_type_completion()
      : modelType === "embedding"
        ? m.model_type_embedding()
        : m.model_type_transcription()
  );

  // --- Handlers ----------------------------------------------------------

  function selectFromCatalog(info: ModelInfo) {
    draft = applyCatalogModelToDraft(draft, info, modelType);
  }

  function commitDraft(event: SubmitEvent) {
    event.preventDefault();
    if (!draftComplete) return;
    if (findDraftCostOverflow(draft) !== null) {
      toast.error(m.cost_value_too_large({ max: MAX_COST_INPUT.toLocaleString("en-US") }));
      return;
    }
    models = [...models, draftToWizardModel(draft)];
    draft = createEmptyDraft(modelType, providerType);
  }
</script>

<div class="flex flex-col gap-6">
  <header>
    <h3 class="text-foreground font-medium">{m.add_models()}</h3>
    <p class="text-muted-foreground text-sm">{m.add_models_description()}</p>
  </header>

  {#if supportStatus === "unsupported"}
    <div
      class="border-warning-default/30 bg-warning-dimmer/30 flex items-start gap-3 rounded-lg border px-4 py-3 text-sm"
      role="alert"
    >
      <TriangleAlert class="text-warning-stronger mt-0.5 size-5 shrink-0" aria-hidden="true" />
      <div>
        <p class="text-warning-stronger font-medium">
          {m.provider_no_support_title({
            providerType: providerLabel,
            modelType: modelTypeLabel
          })}
        </p>
        <p class="text-warning-default mt-0.5">{m.provider_no_support_description()}</p>
      </div>
    </div>
  {/if}

  {#if liveModelsError}
    <div
      class="border-border bg-muted/30 text-muted-foreground rounded-lg border px-4 py-3 text-sm"
    >
      <p>{liveModelsError}</p>
      <p class="mt-1">{m.enter_model_manually()}</p>
    </div>
  {/if}

  <ModelSuggestions models={allModels} selectedName={draft.name} onSelect={selectFromCatalog} />

  <form onsubmit={commitDraft} class="flex flex-col gap-4">
    <ModelDraftForm
      bind:draft
      {modelType}
      {providerType}
      isSelfHosted={selfHosted}
      canAdd={draftComplete}
      showAddAnotherHint={draftComplete && models.length === 0}
    />
  </form>

  <ModelDraftList bind:models {providerId} {modelType} />

  <div class="border-border flex items-center justify-between border-t pt-4">
    <div class="flex items-center gap-4">
      <Button type="button" variant="ghost" onclick={onBack}>
        <ArrowLeft aria-hidden="true" />
        {m.back()}
      </Button>

      <span class="text-muted-foreground text-sm">
        {#if models.length === 0 && !draftComplete}
          {m.add_at_least_one_model()}
        {:else if models.length === 0 && draftComplete}
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
      class="
        text-muted-foreground hover:text-foreground
        focus-visible:ring-ring/50 rounded-sm text-sm underline underline-offset-2
        transition-colors duration-150 focus-visible:ring-3 focus-visible:outline-none
      "
      onclick={onSkip}
    >
      {m.skip_for_now()}
    </button>
  </div>
</div>
