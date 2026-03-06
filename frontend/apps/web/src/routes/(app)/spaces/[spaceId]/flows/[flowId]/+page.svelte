<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { initFlowEditor } from "$lib/features/flows/FlowEditor";
  import { initFlowUserMode, getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import FlowStepList from "$lib/features/flows/components/FlowStepList.svelte";
  import FlowStepEditPanel from "$lib/features/flows/components/FlowStepEditPanel.svelte";
  import FlowGraphPanel from "$lib/features/flows/components/FlowGraphPanel.svelte";
  import FlowFormSchemaEditor from "$lib/features/flows/components/FlowFormSchemaEditor.svelte";
  import FlowUserModeToggle from "$lib/features/flows/components/FlowUserModeToggle.svelte";
  import FlowSaveStatus from "$lib/features/flows/components/FlowSaveStatus.svelte";
  import FlowVersionBadge from "$lib/features/flows/components/FlowVersionBadge.svelte";
  import FlowValidationBanner from "$lib/features/flows/components/FlowValidationBanner.svelte";
  import FlowRunsTable from "$lib/features/flows/components/FlowRunsTable.svelte";
  import FlowRunDialog from "$lib/features/flows/components/FlowRunDialog.svelte";
  import { Button, Input } from "@intric/ui";
  import { IntricError } from "@intric/intric-js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { onDestroy } from "svelte";
  import { slide } from "svelte/transition";
  import FlowDryRun from "$lib/features/flows/components/FlowDryRun.svelte";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import { getFlowFormStats } from "$lib/features/flows/flowFormSchema";

  export let data;
  let publishLoading = false;
  let showRunDialog = false;
  let runsReloadTrigger = 0;
  let hasStepJsonValidationErrors = false;
  let stepJsonValidationFields: string[] = [];
  type BuilderStageId = 1 | 2 | 3 | 4 | 5;
  type FlowMetadataJson = Record<string, unknown>;
  type FlowWizardMetadata = {
    transcription_enabled?: boolean;
    transcription_model?: { id: string } | null;
    transcription_language?: string;
  };
  let builderStage: BuilderStageId = 1;

  const {
    state: { currentSpace }
  } = getSpacesManager();

  const userMode = initFlowUserMode();

  const flowEditor = initFlowEditor({
    flow: data.flow,
    intric: data.intric
  });

  const {
    state: { resource, update, activeStepId, isPublished, saveStatus, validationErrors }
  } = flowEditor;

  const STEP_JSON_FIELD_LABELS: Record<string, () => string> = {
    input_contract: () => m.flow_step_input_contract(),
    output_contract: () => m.flow_step_output_contract(),
    input_config: () => m.flow_step_input_config(),
    output_config: () => m.flow_step_output_config(),
  };

  $: stepJsonValidationSummary = stepJsonValidationFields
    .map((field) => STEP_JSON_FIELD_LABELS[field]?.() ?? field)
    .join(", ");
  $: canPublish =
    !$isPublished &&
    $saveStatus === "saved" &&
    $validationErrors.size === 0 &&
    !hasStepJsonValidationErrors;

  onDestroy(() => {
    flowEditor.destroy();
  });

  let activeTab: "builder" | "history" = "builder";

  const FLOW_BUILDER_STAGES: { id: BuilderStageId; labelKey: () => string }[] = [
    { id: 1, labelKey: () => m.flow_stage_basic_settings() },
    { id: 2, labelKey: () => m.flow_stage_transcription() },
    { id: 3, labelKey: () => m.flow_stage_input_fields() },
    { id: 4, labelKey: () => m.flow_stage_processing_steps() },
    { id: 5, labelKey: () => m.flow_stage_review_test() }
  ];

  $: currentStageIndex = FLOW_BUILDER_STAGES.findIndex((item) => item.id === builderStage);
  $: currentStage = FLOW_BUILDER_STAGES[currentStageIndex];
  $: previousStage = currentStageIndex > 0 ? FLOW_BUILDER_STAGES[currentStageIndex - 1] : null;
  $: nextStage =
    currentStageIndex >= 0 && currentStageIndex < FLOW_BUILDER_STAGES.length - 1
      ? FLOW_BUILDER_STAGES[currentStageIndex + 1]
      : null;
  $: formSchemaFields = (
    ($update.metadata_json as { form_schema?: { fields?: { required?: boolean }[] } } | undefined)?.form_schema
      ?.fields ?? []
  );
  let formSchemaDraftStats: { definedCount: number; requiredCount: number } | null = null;
  $: persistedFormSchemaStats = getFlowFormStats(formSchemaFields);
  $: displayedFormSchemaStats = formSchemaDraftStats ?? persistedFormSchemaStats;
  $: formSchemaDefinedLabel =
    displayedFormSchemaStats.definedCount === 0
      ? m.flow_fields_defined_zero()
      : displayedFormSchemaStats.definedCount === 1
      ? m.flow_fields_defined_singular({ count: displayedFormSchemaStats.definedCount })
      : m.flow_fields_defined_plural({ count: displayedFormSchemaStats.definedCount });
  $: formSchemaRequiredLabel =
    displayedFormSchemaStats.requiredCount === 0
      ? m.flow_fields_required_zero()
      : displayedFormSchemaStats.requiredCount === 1
      ? m.flow_fields_required_singular({ count: displayedFormSchemaStats.requiredCount })
      : m.flow_fields_required_plural({ count: displayedFormSchemaStats.requiredCount });
  $: if (builderStage !== 3 && formSchemaDraftStats !== null) {
    formSchemaDraftStats = null;
  }
  $: hasAudioInputStep = ($update.steps ?? []).some((step) => step.input_type === "audio");
  $: wizardMetadata =
    (((($update.metadata_json as FlowMetadataJson | null | undefined) ?? {})
      .wizard as FlowWizardMetadata | undefined) ?? {});
  $: transcriptionEnabled =
    typeof wizardMetadata.transcription_enabled === "boolean"
      ? wizardMetadata.transcription_enabled
      : hasAudioInputStep;
  $: latestStep = ($update.steps ?? []).at(-1) ?? null;
  $: isTranscriptionSkipped = !transcriptionEnabled;
  $: transcriptionModelId =
    typeof (wizardMetadata as FlowWizardMetadata).transcription_model?.id === "string"
      ? (wizardMetadata as FlowWizardMetadata).transcription_model?.id
      : null;
  $: transcriptionModel =
    ($currentSpace.transcription_models ?? []).find((model) => model.id === transcriptionModelId) ?? null;
  $: selectedTranscriptionModelId =
    transcriptionModel && typeof transcriptionModel.id === "string" ? transcriptionModel.id : null;
  $: if (selectedTranscriptionModelId && selectedTranscriptionModelId !== transcriptionModelId) {
    setWizardMeta({
      transcription_model: { id: selectedTranscriptionModelId }
    });
  }
  $: transcriptionModelMissingInSpace = transcriptionModelId !== null && transcriptionModel === null;
  $: transcriptionLanguage = (wizardMetadata as FlowWizardMetadata).transcription_language ?? "sv";
  $: stepsCount = $update.steps?.length ?? 0;
  $: checklistHasName = ($update.name ?? "").trim().length > 0;
  $: checklistHasSteps = stepsCount > 0;
  $: checklistHasNoErrors = $validationErrors.size === 0 && !hasStepJsonValidationErrors;
  $: isFlowConfigured = checklistHasName && checklistHasSteps;

  function setBuilderStage(stage: BuilderStageId) {
    builderStage = stage;
  }

  function setTranscriptionEnabled(enabled: boolean) {
    const metadata = { ...(($update.metadata_json as FlowMetadataJson | null | undefined) ?? {}) };
    const wizard = { ...((metadata.wizard as Record<string, unknown> | undefined) ?? {}) };
    wizard.transcription_enabled = enabled;
    metadata.wizard = wizard;
    $update.metadata_json = metadata;
  }

  function setWizardMeta(patch: Partial<FlowWizardMetadata>) {
    const metadata = { ...(($update.metadata_json as FlowMetadataJson | null | undefined) ?? {}) };
    metadata.wizard = { ...((metadata.wizard as Record<string, unknown> | undefined) ?? {}), ...patch };
    $update.metadata_json = metadata;
  }

  function goToPreviousStage() {
    if (builderStage > 1) setBuilderStage((builderStage - 1) as BuilderStageId);
  }

  function goToNextStage() {
    if (builderStage < 5) setBuilderStage((builderStage + 1) as BuilderStageId);
  }

  function isStageCompleted(stageId: BuilderStageId): boolean {
    return stageId < builderStage;
  }
</script>

<svelte:head>
  <title>Eneo.ai – {$currentSpace.personal ? m.personal() : $currentSpace.name} – {$resource.name}</title>
</svelte:head>

<Page.Root>
  <Page.Header>
    <Page.Title
      truncate={true}
      parent={{ href: `/spaces/${$currentSpace.routeId}/flows` }}
      title={$resource.name}
    >
    </Page.Title>

    <Page.Tabbar>
      <div role="tablist" class="flex">
        <button
          role="tab"
          aria-selected={activeTab === "builder"}
          aria-controls="panel-builder"
          class="border-b-[3px] px-4 py-2 text-sm font-medium transition-colors duration-200"
          class:border-accent-default={activeTab === "builder"}
          class:text-primary={activeTab === "builder"}
          class:border-transparent={activeTab !== "builder"}
          class:text-secondary={activeTab !== "builder"}
          on:click={() => (activeTab = "builder")}
        >
          {m.flow_builder()}
        </button>
        <button
          role="tab"
          aria-selected={activeTab === "history"}
          aria-controls="panel-history"
          class="border-b-[3px] px-4 py-2 text-sm font-medium transition-colors duration-200"
          class:border-accent-default={activeTab === "history"}
          class:text-primary={activeTab === "history"}
          class:border-transparent={activeTab !== "history"}
          class:text-secondary={activeTab !== "history"}
          on:click={() => (activeTab = "history")}
        >
          {m.flow_history()}
        </button>
      </div>
    </Page.Tabbar>

    <div class="relative z-10 flex min-w-0 shrink items-center gap-2 overflow-hidden">
      <FlowVersionBadge publishedVersion={$resource.published_version} />
      {#if !$isPublished}
        <FlowSaveStatus status={$saveStatus} />
      {/if}
      {#if $isPublished}
        <!-- Hide mode toggle on narrower screens when published (read-only mode) -->
        <div class="hidden xl:block">
          <FlowUserModeToggle />
        </div>
      {:else}
        <FlowUserModeToggle />
      {/if}
      <div class="flex shrink-0 items-center gap-2">
        {#if $isPublished}
          <Button variant="primary" on:click={() => { showRunDialog = true; }}>
            {m.flow_run_trigger()}
          </Button>
          <Button variant="destructive" disabled={publishLoading} on:click={async () => {
            publishLoading = true;
            try {
              const updated = await data.intric.flows.unpublish({ id: $resource.id });
              flowEditor.setResource(updated);
            } catch (e) {
              const msg = e instanceof IntricError ? e.getReadableMessage() : String(e);
              console.error("Unpublish failed:", msg);
              toast.error(msg);
            } finally {
              publishLoading = false;
            }
          }}>{m.flow_unpublish_to_edit()}</Button>
        {:else}
          <Button variant="primary" disabled={!canPublish || publishLoading} on:click={async () => {
            publishLoading = true;
            try {
              await flowEditor.flushAssistantSaves();
              const published = await data.intric.flows.publish({ id: $resource.id });
              flowEditor.setResource(published);
            } catch (e) {
              const msg = e instanceof IntricError ? e.getReadableMessage() : String(e);
              console.error("Publish failed:", msg);
              toast.error(msg);
            } finally {
              publishLoading = false;
            }
          }}>{m.flow_publish()}</Button>
        {/if}
      </div>
    </div>
  </Page.Header>

  <Page.Main>
    <div id="panel-builder" role="tabpanel" class="flex flex-1 flex-col overflow-hidden" class:hidden={activeTab !== "builder"}>
      {#if $isPublished}
        <div class="border-b border-warning-default/40 bg-warning-dimmer px-4 py-2 text-sm text-warning-stronger">
          {m.flow_published_readonly()}
        </div>
      {/if}
      <FlowValidationBanner errors={$validationErrors} />
      {#if hasStepJsonValidationErrors}
        <div class="border-b border-warning-default/40 bg-warning-dimmer px-4 py-2 text-sm text-warning-stronger" role="status">
          {m.flow_step_json_invalid({ fields: stepJsonValidationSummary })}
        </div>
      {/if}

      <!-- Wizard Stepper -->
      <div class="sticky top-0 z-10 border-b border-default bg-primary/95 backdrop-blur-sm px-4 py-3.5 md:px-6">
        <nav class="flex items-center justify-between" aria-label="Flow builder stages">
          <ol class="flex flex-1 items-center">
            {#each FLOW_BUILDER_STAGES as stage, i}
              {@const isActive = builderStage === stage.id}
              {@const isCompleted = isStageCompleted(stage.id)}
              {@const isSkipped = stage.id === 2 && isTranscriptionSkipped}

              {#if i > 0}
                <!-- Connecting line -->
                <div
                  class="mx-1.5 h-0.5 flex-1 transition-colors duration-200 md:mx-3"
                  class:bg-accent-default={isCompleted}
                  class:bg-hover-default={!isCompleted}
                ></div>
              {/if}

              <li class="flex flex-col items-center gap-1">
                <button
                  type="button"
                  class="flex items-center gap-2.5 rounded-lg px-2.5 py-1.5 text-sm transition-all duration-200 hover:bg-hover-dimmer"
                  class:text-primary={isActive}
                  class:font-semibold={isActive}
                  aria-current={isActive ? "step" : undefined}
                  on:click={() => setBuilderStage(stage.id)}
                >
                  <!-- Number circle -->
                  {#if isCompleted}
                    <span class="inline-flex size-8 items-center justify-center rounded-full bg-accent-default text-sm font-semibold text-on-fill transition-colors duration-200">
                      <svg class="size-4" viewBox="0 0 16 16" fill="none">
                        <path d="M3.5 8.5L6.5 11.5L12.5 4.5" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/>
                      </svg>
                    </span>
                  {:else if isActive}
                    <span class="inline-flex size-8 items-center justify-center rounded-full bg-accent-default text-sm font-semibold text-on-fill ring-2 ring-accent-default/20 transition-all duration-200">
                      {stage.id}
                    </span>
                  {:else if isSkipped}
                    <span class="inline-flex size-8 items-center justify-center rounded-full border-2 border-dashed border-default text-sm font-medium text-muted opacity-60 transition-colors duration-200">
                      {stage.id}
                    </span>
                  {:else}
                    <span class="inline-flex size-8 items-center justify-center rounded-full border-2 border-default text-sm font-medium text-secondary transition-colors duration-200">
                      {stage.id}
                    </span>
                  {/if}

                  <!-- Label (hidden on small screens) -->
                  <span
                    class="hidden text-sm md:inline"
                    class:text-primary={isActive}
                    class:text-muted={isSkipped && !isActive}
                    class:italic={isSkipped && !isActive}
                    class:text-secondary={!isActive && !isSkipped}
                  >
                    {stage.labelKey()}
                  </span>
                </button>
              </li>
            {/each}
          </ol>
          <div class="flex shrink-0 items-center gap-2 border-l border-default pl-3 md:gap-2.5 md:pl-5">
            <Button variant="simple" size="default" disabled={!previousStage} on:click={goToPreviousStage}>
              &larr; {m.flow_stage_previous()}
            </Button>
            {#if nextStage}
              <Button variant="primary" size="default" on:click={goToNextStage}>
                {m.flow_stage_next()} &rarr;
              </Button>
            {:else}
              <Button variant="primary" size="default" disabled={!canPublish}
                title={canPublish ? "" : m.flow_publish_not_ready_tooltip()}>
                {m.flow_stage_done()}
              </Button>
            {/if}
          </div>
        </nav>
      </div>

      <div class="flex flex-1 flex-col overflow-hidden p-4 pt-3">
        {#if builderStage === 1}
          <div class="border-default flex-1 overflow-y-auto rounded-xl border p-5 md:p-8">
            <div class="mx-auto max-w-5xl w-full space-y-6">
              <div class="grid gap-6 lg:grid-cols-2">
                <div class="border-default rounded-xl border bg-primary p-6">
                  <h3 class="text-base font-semibold">{m.flow_basic_settings_title()}</h3>
                  <p class="mt-1.5 text-sm text-secondary">
                    {m.flow_basic_settings_desc()}
                  </p>
                  <div class="mt-5 space-y-4">
                    <label class="block text-sm font-medium text-secondary" for="flow-name-input">{m.flow_flow_name()}</label>
                    <input
                      id="flow-name-input"
                      type="text"
                      class="border-default bg-primary ring-default w-full rounded-lg border px-3.5 py-2.5 text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                      value={$update.name ?? ""}
                      disabled={$isPublished}
                      on:input={(event) => {
                        $update.name = event.currentTarget.value;
                      }}
                      placeholder="Exempel: Biståndshandläggning hemtjänst"
                    />
                    <label class="block pt-1 text-sm font-medium text-secondary" for="flow-description-input">{m.flow_flow_description()}</label>
                    <textarea
                      id="flow-description-input"
                      class="border-default bg-primary ring-default min-h-[120px] w-full resize-none rounded-lg border px-3.5 py-2.5 text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                      value={$update.description ?? ""}
                      disabled={$isPublished}
                      on:input={(event) => {
                        $update.description = event.currentTarget.value;
                      }}
                      placeholder={m.flow_description_placeholder()}
                    ></textarea>
                    {#if $userMode === "power_user"}
                      <div class="mt-4 border-t border-default pt-4" transition:slide={{ duration: 200 }}>
                        <label class="block text-sm font-medium text-secondary" for="flow-retention-input">
                          {m.flow_data_retention_label()}
                        </label>
                        <div class="mt-1.5 flex items-center gap-2">
                          <input id="flow-retention-input" type="number" min="1" max="365"
                            class="border-default bg-primary ring-default w-24 rounded-lg border px-3.5 py-2.5 text-sm shadow focus-within:ring-2"
                            value={$update.data_retention_days ?? ""}
                            disabled={$isPublished}
                            placeholder="—"
                            on:input={(e) => {
                              const val = e.currentTarget.value ? parseInt(e.currentTarget.value, 10) : null;
                              $update.data_retention_days = val;
                            }} />
                          <span class="text-sm text-secondary">{m.flow_data_retention_unit()}</span>
                        </div>
                        <p class="mt-1.5 text-xs text-muted">{m.flow_data_retention_desc()}</p>
                      </div>
                    {/if}
                  </div>
                </div>
                {#if isFlowConfigured}
                  <div class="border-default rounded-xl border bg-primary p-6">
                    <h3 class="text-base font-semibold">{m.flow_summary_title()}</h3>
                    <p class="mt-1.5 text-sm text-secondary">{m.flow_summary_desc()}</p>
                    <ul class="mt-5 space-y-4" style="font-variant-numeric: tabular-nums">
                      <li class="flex items-center justify-between">
                        <span class="text-sm text-secondary">{m.flow_summary_steps()}</span>
                        <span class="text-base font-semibold">{stepsCount}</span>
                      </li>
                      <li class="flex items-center justify-between">
                        <span class="text-sm text-secondary">{m.flow_summary_input_fields()}</span>
                        <span class="text-base font-semibold">{formSchemaFields.length}</span>
                      </li>
                      <li class="flex items-center justify-between">
                        <span class="text-sm text-secondary">{m.flow_summary_transcription()}</span>
                        <span class="text-sm font-medium">{transcriptionEnabled ? m.flow_transcription_on() : m.flow_transcription_off()}</span>
                      </li>
                      <li class="flex items-center justify-between">
                        <span class="text-sm text-secondary">{m.flow_summary_validation()}</span>
                        {#if checklistHasNoErrors}
                          <span class="flex items-center gap-1.5 text-positive-stronger">
                            <svg class="size-4" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5L6.5 11.5L12.5 4.5"/></svg>
                          </span>
                        {:else}
                          <span class="text-sm font-medium text-warning-stronger">{m.flow_validation_errors_count({ count: $validationErrors.size })}</span>
                        {/if}
                      </li>
                    </ul>
                    <p class="mt-5 text-sm text-secondary">
                      {$isPublished ? m.flow_status_published_readonly() : m.flow_status_draft()}
                    </p>
                  </div>
                {:else}
                  <div class="border-default rounded-xl border bg-primary p-6">
                    <h3 class="text-base font-semibold">{m.flow_checklist_title()}</h3>
                    <p class="mt-1.5 text-sm text-secondary">{m.flow_checklist_desc()}</p>
                    <ul class="mt-5 space-y-3.5">
                      <li class="flex items-center gap-3 text-sm">
                        <span class="flex size-6 shrink-0 items-center justify-center rounded-full {checklistHasName ? 'bg-positive-dimmer text-positive-stronger' : 'border border-default bg-hover-dimmer text-secondary'}">
                          {#if checklistHasName}<svg class="size-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5L6.5 11.5L12.5 4.5"/></svg>{/if}
                        </span>
                        <span class:text-secondary={!checklistHasName}>{m.flow_checklist_name()}</span>
                      </li>
                      <li class="flex items-center gap-3 text-sm">
                        <span class="flex size-6 shrink-0 items-center justify-center rounded-full {checklistHasSteps ? 'bg-positive-dimmer text-positive-stronger' : 'border border-default bg-hover-dimmer text-secondary'}">
                          {#if checklistHasSteps}<svg class="size-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5L6.5 11.5L12.5 4.5"/></svg>{/if}
                        </span>
                        <span class:text-secondary={!checklistHasSteps}>{m.flow_checklist_steps()}</span>
                      </li>
                      <li class="flex items-center gap-3 text-sm">
                        <span class="flex size-6 shrink-0 items-center justify-center rounded-full {checklistHasSteps ? 'bg-positive-dimmer text-positive-stronger' : 'border border-default bg-hover-dimmer text-secondary'}">
                          {#if checklistHasSteps}<svg class="size-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5L6.5 11.5L12.5 4.5"/></svg>{/if}
                        </span>
                        <span class:text-secondary={!checklistHasSteps}>{m.flow_checklist_instructions()}</span>
                      </li>
                      <li class="flex items-center gap-3 text-sm">
                        <span class="flex size-6 shrink-0 items-center justify-center rounded-full {checklistHasNoErrors ? 'bg-positive-dimmer text-positive-stronger' : 'border border-default bg-hover-dimmer text-secondary'}">
                          {#if checklistHasNoErrors}<svg class="size-3.5" viewBox="0 0 16 16" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round"><path d="M3.5 8.5L6.5 11.5L12.5 4.5"/></svg>{/if}
                        </span>
                        <span class:text-secondary={!checklistHasNoErrors}>{m.flow_checklist_valid()}</span>
                      </li>
                    </ul>
                    <p class="mt-5 text-sm text-secondary">
                      {$isPublished ? m.flow_status_published_readonly() : m.flow_status_draft()}
                    </p>
                  </div>
                {/if}
              </div>
            </div>
          </div>
        {:else if builderStage === 2}
          <div class="border-default flex-1 overflow-y-auto rounded-xl border p-4 md:p-6">
            <div class="mx-auto max-w-3xl w-full space-y-4 pt-4">
              {#if isTranscriptionSkipped}
                <div class="border-default rounded-xl border bg-secondary/30 p-6 text-center">
                  <svg class="mx-auto mb-3 size-8 text-muted/40" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M12 1a3 3 0 0 0-3 3v8a3 3 0 0 0 6 0V4a3 3 0 0 0-3-3z"/>
                    <path d="M19 10v2a7 7 0 0 1-14 0v-2"/>
                    <line x1="12" y1="19" x2="12" y2="23"/>
                    <line x1="8" y1="23" x2="16" y2="23"/>
                  </svg>
                  <h3 class="text-sm font-semibold">{m.flow_transcription_disabled()}</h3>
                  <p class="mx-auto mt-2 max-w-md text-sm text-secondary leading-relaxed">{m.flow_transcription_disabled_subtitle({ variable: "{{transkribering}}" })}</p>
                  <div class="mt-4">
                    <Input.Switch value={transcriptionEnabled} disabled={$isPublished}
                      sideEffect={({ next }) => setTranscriptionEnabled(next)}>
                      {m.flow_transcription_enable()}
                    </Input.Switch>
                  </div>
                  <p class="mt-3 text-xs text-muted">{m.flow_transcription_skip_hint()}</p>
                </div>
                {#if hasAudioInputStep}
                  <div class="rounded-xl border border-warning-default/40 bg-warning-dimmer p-4 text-sm text-warning-stronger">
                    {m.flow_transcription_audio_nudge()}
                  </div>
                {/if}
              {:else}
                <div class="border-default rounded-xl border bg-primary p-5">
                  <div class="flex flex-wrap items-start justify-between gap-3">
                    <div>
                      <h3 class="text-sm font-semibold">{m.flow_transcription_optional_title()}</h3>
                      <p class="mt-1 text-xs text-secondary">
                        {m.flow_transcription_optional_desc({ variable: "{{transkribering}}" })}
                      </p>
                    </div>
                    <Input.Switch value={transcriptionEnabled} disabled={$isPublished}
                      sideEffect={({ next }) => setTranscriptionEnabled(next)}>
                      {m.flow_transcription_enable()}
                    </Input.Switch>
                  </div>
                </div>

                <div class="border-default rounded-xl border bg-primary p-5">
                  <h3 class="text-sm font-semibold">{m.flow_transcription_model_settings()}</h3>
                  <div class="mt-4 grid gap-4 sm:grid-cols-2">
                    <div class="flex flex-col gap-1.5">
                      <span class="text-xs font-medium text-secondary">{m.flow_transcription_model_label()}</span>
                      <SelectAIModelV2
                        bind:selectedModel={transcriptionModel}
                        availableModels={$currentSpace.transcription_models}
                      />
                    </div>
                    <div class="flex flex-col gap-1.5">
                      <label for="flow-transcription-language" class="text-xs font-medium text-secondary">{m.flow_transcription_language_label()}</label>
                      <select class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2"
                        id="flow-transcription-language"
                        value={transcriptionLanguage} disabled={$isPublished}
                        on:change={(e) => setWizardMeta({ transcription_language: e.currentTarget.value })}>
                        <option value="sv">Svenska</option>
                        <option value="en">English</option>
                        <option value="auto">{m.flow_transcription_language_auto()}</option>
                      </select>
                    </div>
                  </div>
                  <div class="mt-4 flex items-center gap-3 opacity-60 pointer-events-none">
                    <Input.Switch value={false} disabled />
                    <span class="text-sm text-secondary">{m.flow_transcription_diarization()}</span>
                    <span class="rounded-full bg-secondary/40 px-2 py-0.5 text-[10px] text-muted">{m.flow_coming_soon()}</span>
                  </div>
                  {#if transcriptionModelMissingInSpace}
                    <div class="mt-4 rounded-lg border border-warning-default/40 bg-warning-dimmer px-3 py-2 text-xs text-warning-stronger">
                      {m.flow_transcription_model_unavailable_warning()}
                    </div>
                  {/if}
                </div>

                {#if hasAudioInputStep}
                  <div class="rounded-xl border border-positive-default/40 bg-positive-dimmer p-4 text-sm text-positive-stronger">
                    {m.flow_transcription_audio_detected()}
                  </div>
                {:else}
                  <div class="rounded-xl border border-default bg-secondary/30 p-4 text-sm text-secondary">
                    {m.flow_transcription_no_audio()}
                  </div>
                {/if}
              {/if}
            </div>
          </div>
        {:else if builderStage === 3}
          <div class="border-default flex-1 overflow-y-auto rounded-xl border p-4 md:p-6">
            <div class="border-default mb-3 flex flex-wrap items-center justify-between gap-2 rounded-lg border bg-primary px-3 py-2 text-sm text-secondary">
              <span>{formSchemaDefinedLabel}</span>
              <span>{formSchemaRequiredLabel}</span>
            </div>
            <FlowFormSchemaEditor
              isPublished={$isPublished}
              on:statsChanged={(e) => {
                formSchemaDraftStats = e.detail;
              }}
            />
          </div>
        {:else if builderStage === 4}
          <!-- Side-by-side list-detail layout -->
          <div class="flex flex-1 flex-col overflow-hidden gap-3 lg:flex-row">
            <div class="border-default w-full overflow-hidden rounded-xl border lg:w-72 lg:shrink-0">
              <FlowStepList
                steps={$update.steps}
                activeStepId={$activeStepId}
                isPublished={$isPublished}
                on:selectStep={async (e) => {
                  try {
                    await flowEditor.flushAssistantSaves();
                  } catch (error) {
                    const message =
                      error instanceof IntricError
                        ? error.getReadableMessage()
                        : "Kunde inte spara stegets ändringar.";
                    toast.error(message);
                  }
                  activeStepId.set(e.detail);
                }}
                on:stepsChanged={async (e) => {
                  try {
                    await flowEditor.applyStepsWithSafeOrderRemap(e.detail);
                  } catch (error) {
                    const message =
                      error instanceof IntricError
                        ? error.getReadableMessage()
                        : "Kunde inte uppdatera stegordning.";
                    toast.error(message);
                  }
                }}
              />
            </div>

            <div class="border-default flex-1 overflow-hidden rounded-xl border">
              <div class="h-full overflow-y-auto">
                <FlowStepEditPanel
                  steps={$update.steps}
                  activeStepId={$activeStepId}
                  isPublished={$isPublished}
                  transcriptionEnabled={transcriptionEnabled}
                  transcriptionModelConfigured={transcriptionModel !== null}
                  transcriptionModelLabel={transcriptionModel?.nickname ?? transcriptionModel?.name ?? null}
                  formSchema={$update.metadata_json?.form_schema as { fields: { name: string; type: string; required?: boolean; options?: string[]; order?: number }[] } | undefined}
                  on:openTranscriptionSettings={() => setBuilderStage(2)}
                  on:jsonValidationChanged={(e) => {
                    hasStepJsonValidationErrors = e.detail.hasErrors;
                    stepJsonValidationFields = e.detail.fields;
                  }}
                  on:stepChanged={(e) => {
                    const { index, step } = e.detail;
                    $update.steps[index] = step;
                    $update.steps = $update.steps;
                  }}
                  on:removeStep={async (e) => {
                    const idx = e.detail;
                    const nextSteps = ($update.steps ?? []).filter((_, i) => i !== idx);
                    nextSteps.forEach((s, i) => {
                      s.step_order = i + 1;
                    });
                    try {
                      await flowEditor.applyStepsWithSafeOrderRemap(nextSteps);
                    } catch (error) {
                      const message =
                        error instanceof IntricError
                          ? error.getReadableMessage()
                          : "Kunde inte ta bort steget.";
                      toast.error(message);
                      return;
                    }
                    const fallbackStep = nextSteps[Math.min(idx, nextSteps.length - 1)]?.id ?? null;
                    activeStepId.set(fallbackStep);
                  }}
                />
              </div>
            </div>
          </div>

          <FlowGraphPanel
            flow={$update}
            activeStepId={$activeStepId}
            on:nodeClick={(e) => activeStepId.set(e.detail)}
          />
        {:else}
          <div class="border-default flex-1 overflow-y-auto rounded-xl border p-5 md:p-8">
            <div class="mx-auto max-w-5xl w-full space-y-6">
              <!-- Pipeline summary -->
              <div class="border-default rounded-xl border bg-primary p-6">
                <h3 class="text-base font-semibold">{m.flow_review_pipeline_title()}</h3>
                <div class="mt-5 flex flex-wrap items-center gap-3">
                  <div class="rounded-lg bg-accent-dimmer px-4 py-2 text-sm font-medium text-accent-stronger">
                    {m.flow_review_input_label()}
                  </div>
                  {#each $update.steps ?? [] as pipeStep}
                    <span class="text-secondary text-lg">&rarr;</span>
                    <div class="flex flex-col items-center rounded-lg border border-default bg-primary px-4 py-2">
                      <span class="text-sm font-medium">{pipeStep.user_description || m.flow_step_fallback_label({ order: String(pipeStep.step_order) })}</span>
                      {#if (pipeStep as any).completion_model?.name}
                        <span class="text-xs text-muted">{(pipeStep as any).completion_model.name}</span>
                      {/if}
                    </div>
                  {/each}
                  <span class="text-secondary text-lg">&rarr;</span>
                  <div class="rounded-lg bg-positive-dimmer px-4 py-2 text-sm font-medium text-positive-stronger">
                    {m.flow_review_output_label()}
                  </div>
                </div>
              </div>

              <!-- Test section -->
              <div class="border-default rounded-xl border bg-primary p-6">
                <h4 class="text-base font-semibold">{m.flow_testing()}</h4>
                {#if $isPublished && $userMode === "power_user"}
                  <p class="mt-1.5 text-sm text-secondary">{m.flow_export_debug_desc()}</p>
                {:else if !$isPublished}
                  <p class="mt-1.5 text-sm text-secondary">{m.flow_dry_run_desc()}</p>
                {/if}
                <div class="mt-5 flex flex-col gap-4">
                  {#if $isPublished}
                    <div class="flex flex-wrap items-center gap-3">
                      <Button variant="primary" size="default" on:click={() => (showRunDialog = true)}>
                        {m.flow_run_trigger()}
                      </Button>
                      <Button variant="outlined" on:click={() => (activeTab = "history")}>
                        {m.flow_show_history()}
                      </Button>
                    </div>
                  {:else}
                    <div class="flex flex-wrap items-center gap-x-3 gap-y-4">
                      <FlowDryRun flow={$resource} />
                      <Button variant="outlined" on:click={() => (activeTab = "history")}>
                        {m.flow_show_history()}
                      </Button>
                      <span class="text-sm text-muted">
                        {$validationErrors.size === 0
                          ? m.flow_publish_status_ready()
                          : m.flow_validation_errors_count({ count: $validationErrors.size })}
                      </span>
                    </div>
                  {/if}
                </div>
              </div>
            </div>
          </div>
        {/if}
      </div>
    </div>

    <div id="panel-history" role="tabpanel" class="flex-1 overflow-y-auto" class:hidden={activeTab !== "history"}>
      <FlowRunsTable flow={$resource} intric={data.intric} visible={activeTab === "history"} reloadTrigger={runsReloadTrigger} />
    </div>
  </Page.Main>
</Page.Root>

<FlowRunDialog
  bind:open={showRunDialog}
  flow={$resource}
  intric={data.intric}
  lastInputPayload={null}
  on:runCreated={() => {
    activeTab = "history";
    runsReloadTrigger++;
  }}
/>

<style>
  @media (prefers-reduced-motion: reduce) {
    :global(*),
    :global(*::before),
    :global(*::after) {
      animation-duration: 0.01ms !important;
      transition-duration: 0.01ms !important;
    }
  }
</style>
