<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getAppContext } from "$lib/core/AppContext";
  import { initFlowEditor } from "$lib/features/flows/FlowEditor";
  import { initFlowUserMode } from "$lib/features/flows/FlowUserMode";
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
  import { Button } from "$lib/components/ui/button/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Badge, Card } from "@eneo/ui";
  import { CheckCircle2 } from "lucide-svelte";
  import { IntricError, type TranscriptionModel } from "@intric/intric-js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";
  import { slide } from "svelte/transition";
  import FlowDryRun from "$lib/features/flows/components/FlowDryRun.svelte";
  import FlowPageHeader from "$lib/features/flows/components/FlowPageHeader.svelte";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import { getFlowFormStats } from "$lib/features/flows/flowFormSchema";
  import FlowAIBuilderEditHost from "$lib/features/flows/ai-builder/FlowAIBuilderEditHost.svelte";
  import {
    resolveAIBuilderApplyNavigation,
    resolveApplyFocusedStepId
  } from "$lib/features/flows/ai-builder/flowAIBuilderApplyNavigation";

  let { data } = $props();
  let publishLoading = $state(false);
  let validationBannerExpanded = $state(false);
  let showRunDialog = $state(false);
  let runsReloadTrigger = $state(0);
  let latestHistoryPayload = $state<Record<string, unknown> | null>(null);
  let pendingRunHighlight = $state<string | null>(null);
  let hasStepJsonValidationErrors = $state(false);
  let stepJsonValidationFields = $state<string[]>([]);
  type BuilderStageId = 1 | 2 | 3 | 4 | 5;
  type FlowMetadataJson = Record<string, unknown>;
  type FlowWizardMetadata = {
    transcription_enabled?: boolean;
    transcription_model?: { id: string } | null;
    transcription_language?: string;
  };
  let builderStage = $state<BuilderStageId>(1);

  const {
    state: { currentSpace }
  } = getSpacesManager();
  const { user } = getAppContext();
  const canUseAIBuilder = user.hasPermission({
    allOf: ["flows_manage", "flows_ai_builder"]
  });

  const userMode = initFlowUserMode();

  const flowEditor = initFlowEditor({
    flow: untrack(() => data.flow),
    intric: untrack(() => data.intric)
  });

  // AI Builder service — initialized lazily when user switches to the AI Builder tab
  let aiBuilderInitialized = $state(false);
  function ensureAIBuilder() {
    if (!aiBuilderInitialized) {
      aiBuilderInitialized = true;
    }
  }

  const {
    state: { resource, update, activeStepId, isPublished, saveStatus, validationErrors }
  } = flowEditor;

  const STEP_JSON_FIELD_LABELS: Record<string, () => string> = {
    input_contract: () => m.flow_step_input_contract(),
    output_contract: () => m.flow_step_output_contract(),
    input_config: () => m.flow_step_input_config(),
    output_config: () => m.flow_step_output_config()
  };

  const stepJsonValidationSummary = $derived(
    stepJsonValidationFields.map((field) => STEP_JSON_FIELD_LABELS[field]?.() ?? field).join(", ")
  );
  const canPublish = $derived(
    !$isPublished &&
      $saveStatus === "saved" &&
      $validationErrors.size === 0 &&
      !hasStepJsonValidationErrors
  );

  $effect(() => {
    return () => {
      flowEditor.destroy();
    };
  });

  let activeTab = $state<"builder" | "history" | "ai-builder">("builder");
  $effect(() => {
    if (!canUseAIBuilder && activeTab === "ai-builder") {
      activeTab = "builder";
    }
  });

  const FLOW_BUILDER_STAGES: { id: BuilderStageId; labelKey: () => string }[] = [
    { id: 1, labelKey: () => m.flow_stage_basic_settings() },
    { id: 2, labelKey: () => m.flow_stage_transcription() },
    { id: 3, labelKey: () => m.flow_stage_input_fields() },
    { id: 4, labelKey: () => m.flow_stage_processing_steps() },
    { id: 5, labelKey: () => m.flow_stage_review_test() }
  ];

  const currentStageIndex = $derived(
    FLOW_BUILDER_STAGES.findIndex((item) => item.id === builderStage)
  );
  const previousStage = $derived(
    currentStageIndex > 0 ? FLOW_BUILDER_STAGES[currentStageIndex - 1] : null
  );
  const nextStage = $derived(
    currentStageIndex >= 0 && currentStageIndex < FLOW_BUILDER_STAGES.length - 1
      ? FLOW_BUILDER_STAGES[currentStageIndex + 1]
      : null
  );
  const formSchemaFields = $derived(
    ($update.metadata_json as { form_schema?: { fields?: { required?: boolean }[] } } | undefined)
      ?.form_schema?.fields ?? []
  );
  let formSchemaDraftStats = $state<{ definedCount: number; requiredCount: number } | null>(null);
  const persistedFormSchemaStats = $derived(getFlowFormStats(formSchemaFields));
  const displayedFormSchemaStats = $derived(formSchemaDraftStats ?? persistedFormSchemaStats);
  const formSchemaDefinedLabel = $derived.by(() => {
    const count = displayedFormSchemaStats.definedCount;
    return count === 0
      ? m.flow_fields_defined_zero()
      : count === 1
        ? m.flow_fields_defined_singular({ count })
        : m.flow_fields_defined_plural({ count });
  });
  const formSchemaRequiredLabel = $derived.by(() => {
    const count = displayedFormSchemaStats.requiredCount;
    return count === 0
      ? m.flow_fields_required_zero()
      : count === 1
        ? m.flow_fields_required_singular({ count })
        : m.flow_fields_required_plural({ count });
  });
  $effect(() => {
    if (builderStage !== 3 && formSchemaDraftStats !== null) {
      formSchemaDraftStats = null;
    }
  });
  const hasAudioInputStep = $derived(
    ($update.steps ?? []).some((step) => step.input_type === "audio")
  );
  const wizardMetadata = $derived(
    ((($update.metadata_json as FlowMetadataJson | null | undefined) ?? {}).wizard as
      | FlowWizardMetadata
      | undefined) ?? {}
  );
  const transcriptionEnabled = $derived(
    typeof wizardMetadata.transcription_enabled === "boolean"
      ? wizardMetadata.transcription_enabled
      : hasAudioInputStep
  );
  const isTranscriptionSkipped = $derived(!transcriptionEnabled);
  const transcriptionModelId = $derived(
    typeof (wizardMetadata as FlowWizardMetadata).transcription_model?.id === "string"
      ? (wizardMetadata as FlowWizardMetadata).transcription_model?.id
      : null
  );
  let transcriptionModel = $state<TranscriptionModel | null>(null);
  const resolvedTranscriptionModel = $derived(
    ($currentSpace.transcription_models ?? []).find((model) => model.id === transcriptionModelId) ??
      null
  );
  // Sync from metadata → local ONLY when the persisted id changes.
  let lastSyncedTranscriptionModelId = $state<string | null | undefined>(undefined);
  $effect(() => {
    if (transcriptionModelId !== lastSyncedTranscriptionModelId) {
      lastSyncedTranscriptionModelId = transcriptionModelId;
      transcriptionModel = resolvedTranscriptionModel;
    }
  });
  const transcriptionModelMissingInSpace = $derived(
    transcriptionModelId !== null && transcriptionModel === null
  );
  const transcriptionLanguage = $derived(
    (wizardMetadata as FlowWizardMetadata).transcription_language ?? "sv"
  );
  const stepsCount = $derived($update.steps?.length ?? 0);
  const checklistHasName = $derived(($update.name ?? "").trim().length > 0);
  const checklistHasSteps = $derived(stepsCount > 0);
  const checklistHasNoErrors = $derived(
    $validationErrors.size === 0 && !hasStepJsonValidationErrors
  );
  const isFlowConfigured = $derived(checklistHasName && checklistHasSteps);

  // Auto-select first step when entering stage 4 with no selection
  $effect(() => {
    if (builderStage === 4 && $activeStepId === null && $update.steps.length > 0) {
      const firstStepId = $update.steps[0]?.id;
      if (firstStepId) activeStepId.set(firstStepId);
    }
  });

  let stageNavigating = $state(false);

  async function navigateToStage(stage: BuilderStageId) {
    if (stage === builderStage || stageNavigating) return;
    stageNavigating = true;
    try {
      await flowEditor.flushAssistantSaves();
      builderStage = stage;
    } catch (e) {
      const msg = e instanceof IntricError ? e.getReadableMessage() : String(e);
      toast.error(msg);
    } finally {
      stageNavigating = false;
    }
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
    metadata.wizard = {
      ...((metadata.wizard as Record<string, unknown> | undefined) ?? {}),
      ...patch
    };
    $update.metadata_json = metadata;
  }

  function goToPreviousStage() {
    if (builderStage > 1) void navigateToStage((builderStage - 1) as BuilderStageId);
  }

  function goToNextStage() {
    if (builderStage < 5) void navigateToStage((builderStage + 1) as BuilderStageId);
  }

  function isStageCompleted(stageId: BuilderStageId): boolean {
    return stageId < builderStage;
  }
</script>

<svelte:head>
  <title
    >Eneo.ai – {$currentSpace.personal ? m.personal() : $currentSpace.name} – {$resource.name}</title
  >
</svelte:head>

<Page.Root>
  <FlowPageHeader
    flowName={$resource.name}
    backHref={`/spaces/${$currentSpace.routeId}/flows`}
    bind:activeTab
    tabs={[
      { value: "builder", label: m.flow_builder() },
      { value: "history", label: m.flow_history() },
      { value: "ai-builder", label: m.ai_builder_tab(), visible: canUseAIBuilder }
    ]}
    onTabChange={(v) => {
      if (v === "ai-builder") ensureAIBuilder();
    }}
  >
    {#snippet actions()}
      <div class="hidden sm:contents">
        <FlowVersionBadge publishedVersion={$resource.published_version} />
        {#if !$isPublished}
          <FlowSaveStatus status={$saveStatus} />
        {/if}
      </div>
      <div class="hidden xl:contents">
        <FlowUserModeToggle />
      </div>
      {#if $isPublished}
        <Button
          variant="default"
          onclick={() => {
            showRunDialog = true;
          }}
        >
          {m.flow_run_trigger()}
        </Button>
        <Button
          variant="destructive"
          disabled={publishLoading}
          onclick={async () => {
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
          }}>{m.flow_unpublish_to_edit()}</Button
        >
      {:else}
        <Button
          variant="default"
          disabled={!canPublish || publishLoading}
          onclick={async () => {
            publishLoading = true;
            try {
              await flowEditor.flushAssistantSaves();
              const published = await data.intric.flows.publish({ id: $resource.id });
              flowEditor.setResource(published);
            } catch (e) {
              const msg = e instanceof IntricError ? e.getReadableMessage() : String(e);
              console.error("Publish failed:", msg);
              toast.error(msg);
              if ($validationErrors.size > 0) {
                validationBannerExpanded = true;
              }
            } finally {
              publishLoading = false;
            }
          }}>{m.flow_publish()}</Button
        >
      {/if}
    {/snippet}
  </FlowPageHeader>

  <Page.Main>
    <div
      id="panel-builder"
      role="tabpanel"
      class="flex flex-1 flex-col overflow-hidden"
      class:hidden={activeTab !== "builder"}
    >
      {#if $isPublished}
        <div
          class="border-warning-default/40 bg-warning-dimmer text-warning-stronger border-b px-4 py-2 text-sm"
        >
          {m.flow_published_readonly()}
        </div>
      {/if}
      <FlowValidationBanner
        errors={$validationErrors}
        steps={$update.steps}
        onNavigateToStep={(stepId) => {
          builderStage = 4;
          activeStepId.set(stepId);
        }}
        bind:isExpanded={validationBannerExpanded}
      />
      {#if hasStepJsonValidationErrors}
        <div
          class="border-warning-default/40 bg-warning-dimmer text-warning-stronger border-b px-4 py-2 text-sm"
          role="status"
        >
          {m.flow_step_json_invalid({ fields: stepJsonValidationSummary })}
        </div>
      {/if}

      <!-- Wizard Stepper -->
      <div class="border-default bg-primary/95 sticky top-0 z-10 border-b backdrop-blur-sm">
        <nav
          class="mx-auto flex max-w-[1600px] items-center gap-2 px-3 py-2.5 sm:px-4 sm:py-3 md:px-6 md:py-3.5"
          aria-label="Flow builder stages"
        >
          <!-- Steps — scrollable on small screens -->
          <ol
            class="flex min-w-0 flex-1 items-center overflow-x-auto [-ms-overflow-style:none] [scrollbar-width:none] [&::-webkit-scrollbar]:hidden"
          >
            {#each FLOW_BUILDER_STAGES as stage, i (stage.id)}
              {@const isActive = builderStage === stage.id}
              {@const isCompleted = isStageCompleted(stage.id)}
              {@const isSkipped = stage.id === 2 && isTranscriptionSkipped}
              {@const isPreviousCompleted =
                i > 0 && isStageCompleted(FLOW_BUILDER_STAGES[i - 1].id)}

              {#if i > 0}
                <div
                  class="mx-1 h-0.5 w-4 shrink-0 transition-colors duration-200 sm:mx-1.5 sm:w-6 lg:mx-3 lg:w-auto lg:flex-1
                    {isPreviousCompleted ? 'bg-accent-default' : 'bg-border-default'}"
                ></div>
              {/if}

              <li class="shrink-0">
                <button
                  type="button"
                  class="hover:bg-hover-dimmer flex items-center gap-1.5 rounded-lg px-1.5 py-1.5 text-sm transition-all duration-200 sm:gap-2 sm:px-2 lg:gap-2.5 lg:px-2.5
                    {isActive ? 'text-primary font-semibold' : ''}"
                  aria-current={isActive ? "step" : undefined}
                  onclick={() => void navigateToStage(stage.id)}
                >
                  {#if isCompleted}
                    <span
                      class="bg-accent-default/15 text-accent-default inline-flex size-7 items-center justify-center rounded-full text-sm font-semibold transition-colors duration-200 sm:size-8"
                    >
                      <svg class="size-3.5 sm:size-4" viewBox="0 0 16 16" fill="none">
                        <path
                          d="M3.5 8.5L6.5 11.5L12.5 4.5"
                          stroke="currentColor"
                          stroke-width="2"
                          stroke-linecap="round"
                          stroke-linejoin="round"
                        />
                      </svg>
                    </span>
                  {:else if isActive}
                    <span
                      class="bg-accent-default text-on-fill ring-accent-default/20 inline-flex size-7 items-center justify-center rounded-full text-sm font-semibold ring-2 transition-all duration-200 sm:size-8"
                    >
                      {stage.id}
                    </span>
                  {:else if isSkipped}
                    <span
                      class="border-default text-muted inline-flex size-7 items-center justify-center rounded-full border-2 border-dashed text-sm font-medium opacity-60 transition-colors duration-200 sm:size-8"
                    >
                      {stage.id}
                    </span>
                  {:else}
                    <span
                      class="border-default text-muted inline-flex size-7 items-center justify-center rounded-full border-2 text-sm font-medium transition-colors duration-200 sm:size-8"
                    >
                      {stage.id}
                    </span>
                  {/if}

                  <!-- Label — only on large screens -->
                  <span
                    class="hidden text-sm whitespace-nowrap lg:inline
                      {isActive
                      ? 'text-primary font-semibold'
                      : isSkipped
                        ? 'text-muted italic'
                        : isCompleted
                          ? 'text-secondary'
                          : 'text-muted'}"
                  >
                    {stage.labelKey()}
                  </span>
                </button>
              </li>
            {/each}
          </ol>

          <!-- Navigation buttons — always visible, never overflow -->
          <div
            class="border-default flex shrink-0 items-center gap-1.5 border-l pl-2.5 sm:gap-2 sm:pl-3 md:pl-5"
          >
            <Button
              variant="ghost"
              size="sm"
              disabled={!previousStage || stageNavigating}
              onclick={goToPreviousStage}
            >
              &larr; <span class="hidden lg:inline">{m.flow_stage_previous()}</span>
            </Button>
            {#if nextStage}
              <Button
                variant="default"
                size="sm"
                disabled={stageNavigating}
                onclick={goToNextStage}
              >
                <span class="hidden lg:inline">{m.flow_stage_next()}</span> &rarr;
              </Button>
            {:else}
              <Button
                variant="default"
                size="sm"
                disabled={!canPublish}
                title={canPublish ? "" : m.flow_publish_not_ready_tooltip()}
              >
                {m.flow_stage_done()}
              </Button>
            {/if}
          </div>
        </nav>
      </div>

      <div class="flex flex-1 flex-col overflow-hidden p-4 pt-3">
        {#if builderStage === 1}
          <div class="flex-1 overflow-y-auto p-5 md:p-8">
            <div class="mx-auto w-full max-w-6xl space-y-6">
              <div class="grid gap-6 lg:grid-cols-2">
                <div class="border-default bg-primary rounded-xl border p-6">
                  <h3 class="text-base font-semibold">{m.flow_basic_settings_title()}</h3>
                  <p class="text-secondary mt-1.5 text-sm">
                    {m.flow_basic_settings_desc()}
                  </p>
                  <div class="mt-5 flex flex-col gap-5">
                    <div class="flex flex-col gap-1.5">
                      <label class="text-secondary text-sm font-medium" for="flow-name-input"
                        >{m.flow_flow_name()}</label
                      >
                      <input
                        id="flow-name-input"
                        type="text"
                        class="border-default bg-primary ring-default w-full rounded-lg border px-3.5 py-2.5 text-sm shadow transition-shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                        value={$update.name ?? ""}
                        disabled={$isPublished}
                        oninput={(event) => {
                          $update.name = event.currentTarget.value;
                        }}
                        placeholder={m.flow_flow_name()}
                      />
                    </div>
                    <div class="flex flex-col gap-1.5">
                      <label class="text-secondary text-sm font-medium" for="flow-description-input"
                        >{m.flow_flow_description()}</label
                      >
                      <textarea
                        id="flow-description-input"
                        class="border-default bg-primary ring-default min-h-[120px] w-full resize-none rounded-lg border px-3.5 py-2.5 text-sm shadow transition-shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                        value={$update.description ?? ""}
                        disabled={$isPublished}
                        oninput={(event) => {
                          $update.description = event.currentTarget.value;
                        }}
                        placeholder={m.flow_description_placeholder()}
                      ></textarea>
                    </div>
                    {#if $userMode === "power_user"}
                      <div
                        class="border-default mt-4 border-t pt-4"
                        transition:slide={{ duration: 200 }}
                      >
                        <label
                          class="text-secondary block text-sm font-medium"
                          for="flow-retention-input"
                        >
                          {m.flow_data_retention_label()}
                        </label>
                        <div class="mt-1.5 flex items-center gap-2">
                          <input
                            id="flow-retention-input"
                            type="number"
                            min="1"
                            max="365"
                            class="border-default bg-primary ring-default w-24 rounded-lg border px-3.5 py-2.5 text-sm shadow focus-within:ring-2"
                            value={$update.data_retention_days ?? ""}
                            disabled={$isPublished}
                            placeholder="—"
                            oninput={(e) => {
                              const val = e.currentTarget.value
                                ? parseInt(e.currentTarget.value, 10)
                                : null;
                              $update.data_retention_days = val;
                            }}
                          />
                          <span class="text-secondary text-sm">{m.flow_data_retention_unit()}</span>
                        </div>
                        <p class="text-muted mt-1.5 text-sm">{m.flow_data_retention_desc()}</p>
                      </div>
                    {/if}
                  </div>
                </div>
                {#if isFlowConfigured}
                  <Card.Root size="sm">
                    <Card.Header>
                      <Card.Title class="font-semibold">{m.flow_summary_title()}</Card.Title>
                      <Card.Description>{m.flow_summary_desc()}</Card.Description>
                    </Card.Header>
                    <Card.Content>
                      <ul class="space-y-3" style="font-variant-numeric: tabular-nums">
                        <li class="flex items-center justify-between">
                          <span class="text-secondary text-sm">{m.flow_summary_steps()}</span>
                          <span class="text-base font-semibold">{stepsCount}</span>
                        </li>
                        <li class="flex items-center justify-between">
                          <span class="text-secondary text-sm">{m.flow_summary_input_fields()}</span
                          >
                          <span class="text-base font-semibold">{formSchemaFields.length}</span>
                        </li>
                        <li class="flex items-center justify-between">
                          <span class="text-secondary text-sm"
                            >{m.flow_summary_transcription()}</span
                          >
                          <span class="text-sm font-medium"
                            >{transcriptionEnabled
                              ? m.flow_transcription_on()
                              : m.flow_transcription_off()}</span
                          >
                        </li>
                        <li class="flex items-center justify-between">
                          <span class="text-secondary text-sm">{m.flow_summary_validation()}</span>
                          {#if checklistHasNoErrors}
                            <span class="text-positive-stronger flex items-center gap-1.5">
                              <svg
                                class="size-4"
                                viewBox="0 0 16 16"
                                fill="none"
                                stroke="currentColor"
                                stroke-width="2.5"
                                stroke-linecap="round"
                                stroke-linejoin="round"><path d="M3.5 8.5L6.5 11.5L12.5 4.5" /></svg
                              >
                            </span>
                          {:else}
                            <span class="text-warning-stronger text-sm font-medium"
                              >{m.flow_validation_errors_count({
                                count: $validationErrors.size
                              })}</span
                            >
                          {/if}
                        </li>
                        <li class="flex items-center justify-between">
                          <span class="text-secondary text-sm">{m.flow_summary_status()}</span>
                          {#if $isPublished}
                            <Badge
                              variant="outline"
                              class="border-positive-default/25 bg-positive-dimmer/50 text-positive-stronger"
                              >{m.flow_status_published_readonly()}</Badge
                            >
                          {:else}
                            <Badge
                              variant="outline"
                              class="border-warning-default/25 bg-warning-dimmer/50 text-warning-stronger"
                              >{m.flow_status_draft()}</Badge
                            >
                          {/if}
                        </li>
                      </ul>
                    </Card.Content>
                  </Card.Root>
                {:else}
                  <div class="border-default bg-primary rounded-xl border p-6">
                    <h3 class="text-base font-semibold">{m.flow_checklist_title()}</h3>
                    <p class="text-secondary mt-1.5 text-sm">{m.flow_checklist_desc()}</p>
                    <ul class="mt-5 space-y-3.5">
                      <li class="flex items-center gap-3 text-sm">
                        <span
                          class="flex size-6 shrink-0 items-center justify-center rounded-full {checklistHasName
                            ? 'bg-positive-dimmer text-positive-stronger'
                            : 'border-default bg-hover-dimmer text-secondary border'}"
                        >
                          {#if checklistHasName}<svg
                              class="size-3.5"
                              viewBox="0 0 16 16"
                              fill="none"
                              stroke="currentColor"
                              stroke-width="2.5"
                              stroke-linecap="round"
                              stroke-linejoin="round"><path d="M3.5 8.5L6.5 11.5L12.5 4.5" /></svg
                            >{/if}
                        </span>
                        <span class:text-secondary={!checklistHasName}
                          >{m.flow_checklist_name()}</span
                        >
                      </li>
                      <li class="flex items-center gap-3 text-sm">
                        <span
                          class="flex size-6 shrink-0 items-center justify-center rounded-full {checklistHasSteps
                            ? 'bg-positive-dimmer text-positive-stronger'
                            : 'border-default bg-hover-dimmer text-secondary border'}"
                        >
                          {#if checklistHasSteps}<svg
                              class="size-3.5"
                              viewBox="0 0 16 16"
                              fill="none"
                              stroke="currentColor"
                              stroke-width="2.5"
                              stroke-linecap="round"
                              stroke-linejoin="round"><path d="M3.5 8.5L6.5 11.5L12.5 4.5" /></svg
                            >{/if}
                        </span>
                        <span class:text-secondary={!checklistHasSteps}
                          >{m.flow_checklist_steps()}</span
                        >
                      </li>
                      <li class="flex items-center gap-3 text-sm">
                        <span
                          class="flex size-6 shrink-0 items-center justify-center rounded-full {checklistHasSteps
                            ? 'bg-positive-dimmer text-positive-stronger'
                            : 'border-default bg-hover-dimmer text-secondary border'}"
                        >
                          {#if checklistHasSteps}<svg
                              class="size-3.5"
                              viewBox="0 0 16 16"
                              fill="none"
                              stroke="currentColor"
                              stroke-width="2.5"
                              stroke-linecap="round"
                              stroke-linejoin="round"><path d="M3.5 8.5L6.5 11.5L12.5 4.5" /></svg
                            >{/if}
                        </span>
                        <span class:text-secondary={!checklistHasSteps}
                          >{m.flow_checklist_instructions()}</span
                        >
                      </li>
                      <li class="flex items-center gap-3 text-sm">
                        <span
                          class="flex size-6 shrink-0 items-center justify-center rounded-full {checklistHasNoErrors
                            ? 'bg-positive-dimmer text-positive-stronger'
                            : 'border-default bg-hover-dimmer text-secondary border'}"
                        >
                          {#if checklistHasNoErrors}<svg
                              class="size-3.5"
                              viewBox="0 0 16 16"
                              fill="none"
                              stroke="currentColor"
                              stroke-width="2.5"
                              stroke-linecap="round"
                              stroke-linejoin="round"><path d="M3.5 8.5L6.5 11.5L12.5 4.5" /></svg
                            >{/if}
                        </span>
                        <span class:text-secondary={!checklistHasNoErrors}
                          >{m.flow_checklist_valid()}</span
                        >
                      </li>
                    </ul>
                    <div class="mt-5">
                      {#if $isPublished}
                        <Badge
                          variant="outline"
                          class="border-positive-default/25 bg-positive-dimmer/50 text-positive-stronger"
                          >{m.flow_status_published_readonly()}</Badge
                        >
                      {:else}
                        <Badge
                          variant="outline"
                          class="border-warning-default/25 bg-warning-dimmer/50 text-warning-stronger"
                          >{m.flow_status_draft()}</Badge
                        >
                      {/if}
                    </div>
                  </div>
                {/if}
              </div>
            </div>
          </div>
        {:else if builderStage === 2}
          <div class="flex-1 overflow-y-auto p-4 md:p-6">
            <div class="mx-auto w-full max-w-2xl space-y-5 pt-4">
              <!-- Main transcription card — single unified card for all states -->
              <div
                class="bg-primary rounded-xl border transition-colors duration-300 {transcriptionEnabled
                  ? 'border-accent-default/30'
                  : 'border-default'}"
              >
                <!-- Header: toggle row -->
                <div class="flex items-center justify-between px-5 py-4">
                  <div class="min-w-0">
                    <h3 class="text-[0.9375rem] font-semibold tracking-[-0.01em]">
                      {m.flow_transcription_optional_title()}
                    </h3>
                    <p class="text-secondary mt-0.5 text-sm leading-relaxed">
                      {m.flow_transcription_optional_desc_simple()}
                    </p>
                  </div>
                  <label
                    class="flex shrink-0 cursor-pointer items-center gap-2.5 pl-4"
                    for="transcription-toggle"
                  >
                    <span class="text-secondary text-sm"
                      >{transcriptionEnabled
                        ? m.flow_transcription_on()
                        : m.flow_transcription_off()}</span
                    >
                    <Switch
                      id="transcription-toggle"
                      checked={transcriptionEnabled}
                      disabled={$isPublished}
                      onCheckedChange={(checked) => setTranscriptionEnabled(checked)}
                    />
                  </label>
                </div>

                <!-- Settings: shown when enabled -->
                {#if transcriptionEnabled}
                  <div
                    class="border-default border-t px-5 py-4"
                    transition:slide={{ duration: 200 }}
                  >
                    <div class="grid gap-4 sm:grid-cols-2">
                      <div class="flex flex-col gap-1.5">
                        <label
                          for="flow-transcription-model"
                          class="text-secondary text-sm font-medium"
                          >{m.flow_transcription_model_label()}</label
                        >
                        <SelectAIModelV2
                          bind:selectedModel={transcriptionModel}
                          availableModels={$currentSpace.transcription_models}
                          dropdownLabel={m.flow_transcription_model_label()}
                          onchange={() => {
                            if (transcriptionModel?.id) {
                              setWizardMeta({ transcription_model: { id: transcriptionModel.id } });
                            }
                          }}
                        />
                      </div>
                      <div class="flex flex-col gap-1.5">
                        <label
                          for="flow-transcription-language"
                          class="text-secondary text-sm font-medium"
                          >{m.flow_transcription_language_label()}</label
                        >
                        <select
                          class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2"
                          id="flow-transcription-language"
                          value={transcriptionLanguage}
                          disabled={$isPublished}
                          onchange={(e) =>
                            setWizardMeta({ transcription_language: e.currentTarget.value })}
                        >
                          <option value="sv">Svenska</option>
                          <option value="en">English</option>
                          <option value="auto">{m.flow_transcription_language_auto()}</option>
                        </select>
                      </div>
                    </div>
                    {#if transcriptionModelMissingInSpace}
                      <div
                        class="border-warning-default/40 bg-warning-dimmer text-warning-stronger mt-4 rounded-lg border px-3 py-2 text-sm"
                      >
                        {m.flow_transcription_model_unavailable_warning()}
                      </div>
                    {/if}
                  </div>
                {/if}
              </div>

              <!-- Audio status hint — only when it adds real information -->
              {#if !transcriptionEnabled && hasAudioInputStep}
                <div
                  class="border-warning-default/30 bg-warning-dimmer/50 text-warning-stronger flex items-start gap-3 rounded-xl border px-4 py-3.5 text-sm leading-relaxed"
                >
                  <svg class="mt-0.5 size-4 shrink-0" viewBox="0 0 16 16" fill="currentColor">
                    <path
                      d="M8.982 1.566a1.13 1.13 0 0 0-1.96 0L.165 13.233c-.457.778.091 1.767.98 1.767h13.713c.889 0 1.438-.99.98-1.767L8.982 1.566zM8 5c.535 0 .954.462.9.995l-.35 3.507a.552.552 0 0 1-1.1 0L7.1 5.995A.905.905 0 0 1 8 5zm.002 6a1 1 0 1 1 0 2 1 1 0 0 1 0-2z"
                    />
                  </svg>
                  {m.flow_transcription_audio_nudge()}
                </div>
              {/if}

              {#if !transcriptionEnabled && !hasAudioInputStep}
                <p class="text-muted px-1 text-sm">{m.flow_transcription_skip_hint()}</p>
              {/if}
            </div>
          </div>
        {:else if builderStage === 3}
          <div class="flex-1 overflow-y-auto p-4 md:p-6">
            <div class="mx-auto w-full max-w-3xl pt-2">
              <FlowFormSchemaEditor
                isPublished={$isPublished}
                onStatsChanged={(detail) => {
                  formSchemaDraftStats = detail;
                }}
              />
            </div>
          </div>
        {:else if builderStage === 4}
          <!-- Side-by-side list-detail layout -->
          <div
            class="mx-auto flex w-full max-w-[1600px] flex-1 flex-col gap-3 overflow-hidden lg:flex-row"
          >
            <div
              class="border-default max-h-[40vh] w-full overflow-hidden rounded-xl border lg:max-h-none lg:w-80 lg:shrink-0 xl:w-[340px]"
            >
              <FlowStepList
                steps={$update.steps}
                activeStepId={$activeStepId}
                isPublished={$isPublished}
                validationErrors={$validationErrors}
                onBuildWithAI={canUseAIBuilder
                  ? () => {
                      ensureAIBuilder();
                      activeTab = "ai-builder";
                    }
                  : undefined}
                onSelectStep={async (stepId) => {
                  try {
                    await flowEditor.flushAssistantSaves();
                  } catch (error) {
                    const message =
                      error instanceof IntricError
                        ? error.getReadableMessage()
                        : "Kunde inte spara stegets ändringar.";
                    toast.error(message);
                  }
                  activeStepId.set(stepId);
                }}
                onStepsChanged={async (updatedSteps) => {
                  try {
                    await flowEditor.applyStepsWithSafeOrderRemap(updatedSteps);
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

            <div
              class="border-default flex-1 overflow-hidden rounded-xl border lg:max-w-[900px] 2xl:max-w-[1000px]"
            >
              <div class="h-full overflow-y-auto">
                <FlowStepEditPanel
                  steps={$update.steps}
                  activeStepId={$activeStepId}
                  isPublished={$isPublished}
                  {transcriptionEnabled}
                  transcriptionModelConfigured={transcriptionModel !== null}
                  transcriptionModelLabel={transcriptionModel?.nickname ??
                    transcriptionModel?.name ??
                    null}
                  formSchema={$update.metadata_json?.form_schema as
                    | {
                        fields: {
                          name: string;
                          type: string;
                          required?: boolean;
                          options?: string[];
                          order?: number;
                        }[];
                      }
                    | undefined}
                  onOpenTranscriptionSettings={() => void navigateToStage(2)}
                  onJsonValidationChanged={(detail) => {
                    hasStepJsonValidationErrors = detail.hasErrors;
                    stepJsonValidationFields = detail.fields;
                  }}
                  onStepChanged={(detail) => {
                    const { index, step } = detail;
                    $update.steps[index] = step;
                    $update.steps = $update.steps;
                  }}
                  onRemoveStep={async (idx) => {
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
            onNodeClick={(stepId) => activeStepId.set(stepId)}
          />
        {:else}
          <div class="flex-1 overflow-y-auto p-5 md:p-8">
            <div class="mx-auto w-full max-w-6xl space-y-6">
              <!-- Pipeline summary -->
              <div class="border-default bg-primary rounded-xl border p-6">
                <h3 class="text-base font-semibold">{m.flow_review_pipeline_title()}</h3>
                <div class="mt-5 flex flex-wrap items-center gap-3">
                  <div
                    class="bg-accent-dimmer text-accent-stronger rounded-lg px-4 py-2 text-sm font-medium"
                  >
                    {m.flow_review_input_label()}
                  </div>
                  {#each $update.steps ?? [] as pipeStep (pipeStep.id ?? pipeStep.step_order)}
                    <span class="text-secondary text-lg">&rarr;</span>
                    {@const completionModel =
                      "completion_model" in pipeStep
                        ? (pipeStep as { completion_model?: { name?: string | null } | null })
                            .completion_model
                        : null}
                    <div
                      class="border-default bg-primary flex flex-col items-center rounded-lg border px-4 py-2"
                    >
                      <span class="text-sm font-medium"
                        >{pipeStep.user_description ||
                          m.flow_step_fallback_label({ order: String(pipeStep.step_order) })}</span
                      >
                      {#if completionModel?.name}
                        <span class="text-muted text-xs">{completionModel.name}</span>
                      {/if}
                    </div>
                  {/each}
                  <span class="text-secondary text-lg">&rarr;</span>
                  <div
                    class="bg-positive-dimmer text-positive-stronger rounded-lg px-4 py-2 text-sm font-medium"
                  >
                    {m.flow_review_output_label()}
                  </div>
                </div>
              </div>

              <!-- Test section -->
              <div class="border-default bg-primary rounded-xl border p-6">
                <h4 class="text-base font-semibold">{m.flow_testing()}</h4>
                {#if $isPublished && $userMode === "power_user"}
                  <p class="text-secondary mt-1.5 text-sm">{m.flow_export_debug_desc()}</p>
                {:else if !$isPublished}
                  <p class="text-secondary mt-1.5 text-sm">{m.flow_dry_run_desc()}</p>
                {/if}
                <div class="mt-5 flex flex-col gap-4">
                  {#if $isPublished}
                    <div class="flex flex-wrap items-center gap-3">
                      <Button
                        variant="default"
                        size="default"
                        onclick={() => (showRunDialog = true)}
                      >
                        {m.flow_run_trigger()}
                      </Button>
                      <Button variant="outline" onclick={() => (activeTab = "history")}>
                        {m.flow_show_history()}
                      </Button>
                    </div>
                  {:else}
                    <div class="flex flex-wrap items-center gap-x-3 gap-y-4">
                      <FlowDryRun flow={$resource} />
                      <Button variant="outline" onclick={() => (activeTab = "history")}>
                        {m.flow_show_history()}
                      </Button>
                      {#if $validationErrors.size === 0}
                        <Badge
                          variant="outline"
                          class="border-positive-default/25 bg-positive-dimmer/50 text-positive-stronger gap-1.5"
                        >
                          <CheckCircle2 class="size-3.5" />
                          {m.flow_publish_status_ready()}
                        </Badge>
                      {:else}
                        <span class="text-muted text-sm">
                          {m.flow_validation_errors_count({ count: $validationErrors.size })}
                        </span>
                      {/if}
                    </div>
                  {/if}
                </div>
              </div>
            </div>
          </div>
        {/if}
      </div>
    </div>

    {#if canUseAIBuilder && aiBuilderInitialized}
      <div
        id="panel-ai-builder"
        role="tabpanel"
        class="flex min-h-0 flex-1 flex-col overflow-hidden"
        class:hidden={activeTab !== "ai-builder"}
      >
        <FlowAIBuilderEditHost
          intric={data.intric}
          spaceId={$currentSpace.id}
          flowId={$resource.id}
          onapplied={async (detail) => {
            try {
              const updated = await data.intric.flows.get({ id: detail.flow_id });
              flowEditor.setResource(updated);
              const navigation = resolveAIBuilderApplyNavigation({
                stepCount: updated.steps?.length ?? 0,
                requestedFocusStepIndex: detail.focusStepIndex
              });
              activeTab = navigation.activeTab;
              builderStage = navigation.builderStage;
              const focusedStepId = resolveApplyFocusedStepId(
                updated.steps ?? [],
                navigation.focusStepIndex
              );
              if (focusedStepId) {
                activeStepId.set(focusedStepId);
              }
            } catch (err) {
              console.error("Failed to refresh flow after apply:", err);
            }
          }}
        />
      </div>
    {/if}

    <div
      id="panel-history"
      role="tabpanel"
      class="flex-1 overflow-y-auto"
      class:hidden={activeTab !== "history"}
    >
      <FlowRunsTable
        flow={$resource}
        intric={data.intric}
        visible={activeTab === "history"}
        reloadTrigger={runsReloadTrigger}
        bind:latestRunPayload={latestHistoryPayload}
        bind:pendingHighlightRunId={pendingRunHighlight}
      />
    </div>
  </Page.Main>
</Page.Root>

<FlowRunDialog
  bind:open={showRunDialog}
  flow={$resource}
  intric={data.intric}
  lastInputPayload={latestHistoryPayload}
  onRunCreated={(detail) => {
    activeTab = "history";
    pendingRunHighlight = detail.runId;
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
