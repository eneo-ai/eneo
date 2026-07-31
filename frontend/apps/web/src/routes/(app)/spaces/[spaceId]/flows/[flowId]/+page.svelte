<script lang="ts">
  import { Page } from "$lib/components/layout";
  import { browser } from "$app/environment";
  import { replaceState } from "$app/navigation";
  import { page } from "$app/state";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getAppContext } from "$lib/core/AppContext";
  import { getFlowWizardMetadata, initFlowEditor } from "$lib/features/flows/FlowEditor";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
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
  import FlowPackageExportDialog from "$lib/features/flows/components/FlowPackageExportDialog.svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Textarea } from "$lib/components/ui/textarea/index.js";
  import * as Field from "$lib/components/ui/field/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import CheckCircle2 from "lucide-svelte/icons/check-circle-2";
  import CircleAlert from "lucide-svelte/icons/circle-alert";
  import {
    EneoError,
    type FlowRun,
    type FlowRunRetention,
    type TranscriptionModel
  } from "@eneo/eneo-js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { untrack } from "svelte";
  import { slide } from "svelte/transition";
  import FlowDryRun from "$lib/features/flows/components/FlowDryRun.svelte";
  import FlowPageHeader from "$lib/features/flows/components/FlowPageHeader.svelte";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import FlowAIBuilderEditHost from "$lib/features/flows/ai-builder/FlowAIBuilderEditHost.svelte";
  import { resolveFlowCareDataPolicy } from "$lib/features/flows/flowCareDataPolicy";
  import {
    resolveAIBuilderApplyNavigation,
    resolveApplyFocusedStepId
  } from "$lib/features/flows/ai-builder/flowAIBuilderApplyNavigation";
  import {
    getFlowFormSchemaFields,
    getFlowFormSchemaMetadata
  } from "$lib/features/flows/flowFormSchema";

  let { data } = $props();
  let publishLoading = $state(false);
  let showUnpublishDialog = $state(false);
  // Which affordance opened the unpublish dialog: "edit" frames it as the
  // path to editing; "service" is the deliberate take-out-of-service action.
  let unpublishIntent = $state<"edit" | "service">("edit");
  let validationBannerExpanded = $state(false);
  let showRunDialog = $state(false);
  let runsReloadTrigger = $state(0);
  let optimisticHistoryRuns = $state<FlowRun[]>([]);
  let latestHistoryPayload = $state<Record<string, unknown> | null>(null);
  let hasStepJsonValidationErrors = $state(false);
  let stepJsonValidationFields = $state<string[]>([]);
  type BuilderStageId = 1 | 2 | 3 | 4 | 5;
  let builderStage = $state<BuilderStageId>(1);

  const {
    state: { currentSpace }
  } = getSpacesManager();
  const { user } = getAppContext();
  const canUseAIBuilder = user.hasPermission({
    allOf: ["flows_manage", "flows_ai_builder"]
  });

  const userMode = getFlowUserMode();

  const flowEditor = initFlowEditor({
    flow: untrack(() => data.flow),
    eneo: untrack(() => data.eneo)
  });

  // AI Builder service — initialized lazily when user switches to the AI Builder tab
  let aiBuilderInitialized = $state(false);
  function ensureAIBuilder() {
    if (!aiBuilderInitialized) {
      aiBuilderInitialized = true;
    }
  }

  const {
    state: {
      resource,
      update,
      activeStepId,
      isPublished,
      canEditDataRetentionDays,
      saveStatus,
      validationErrors
    }
  } = flowEditor;
  const careDataPolicy = $derived(resolveFlowCareDataPolicy($resource.metadata_json));
  const runHistoryRetention = $derived($resource.run_history_retention);

  function retentionActivationSourceLabel(
    source: NonNullable<FlowRunRetention>["activation_sources"][number]
  ): string {
    return source === "organization"
      ? m.flow_retention_contributor_organization()
      : m.flow_retention_contributor_classification();
  }

  function retentionBarrierSourceLabel(
    source: NonNullable<FlowRunRetention>["barrier_sources"][number]
  ): string {
    switch (source) {
      case "organization_minimum":
        return m.flow_retention_contributor_organization_minimum();
      case "classification_minimum":
        return m.flow_retention_contributor_classification_minimum();
      case "organization_no_purge":
        return m.flow_retention_source_organization_no_purge();
      case "classification_no_purge":
        return m.flow_retention_source_classification_no_purge();
    }
  }

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

  type FlowPageTab = "builder" | "history" | "ai-builder";

  function isFlowPageTab(value: string | null): value is FlowPageTab {
    return value === "builder" || value === "history" || value === "ai-builder";
  }

  function resolveInitialTab(): FlowPageTab {
    const urlTab = page.url.searchParams.get("tab");
    return isFlowPageTab(urlTab) ? urlTab : "builder";
  }

  let pendingPersistedTab: FlowPageTab | null = null;

  function persistActiveTab(tab: FlowPageTab) {
    if (!browser) return;

    const url = new URL(page.url);
    url.searchParams.set("tab", tab);
    pendingPersistedTab = tab;
    // resolve() requires a typed RouteId literal; this tab URL preserves the current
    // dynamic flow route and only changes query state.
    // eslint-disable-next-line svelte/no-navigation-without-resolve
    replaceState(url, { ...page.state, tab });
    setTimeout(() => {
      if (pendingPersistedTab === tab) pendingPersistedTab = null;
    }, 0);
  }

  function setActiveTab(tab: FlowPageTab) {
    activeTab = tab;
    persistActiveTab(tab);
  }

  let activeTab = $state<FlowPageTab>(resolveInitialTab());
  $effect(() => {
    if (!canUseAIBuilder && activeTab === "ai-builder") {
      setActiveTab("builder");
    }
  });

  $effect(() => {
    if (activeTab === "ai-builder" && canUseAIBuilder) {
      ensureAIBuilder();
    }
  });

  $effect(() => {
    const urlTab = page.url.searchParams.get("tab");
    if (!isFlowPageTab(urlTab) || urlTab === activeTab) return;
    if (pendingPersistedTab && urlTab !== pendingPersistedTab) return;
    if (pendingPersistedTab === urlTab) pendingPersistedTab = null;
    if (urlTab === "ai-builder" && !canUseAIBuilder) {
      setActiveTab("builder");
      return;
    }
    activeTab = urlTab;
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
  const formSchemaMetadata = $derived(getFlowFormSchemaMetadata($update.metadata_json));
  const formSchemaFields = $derived(getFlowFormSchemaFields($update.metadata_json));
  let formSchemaDraftStats = $state<{ definedCount: number; requiredCount: number } | null>(null);
  $effect(() => {
    if (builderStage !== 3 && formSchemaDraftStats !== null) {
      formSchemaDraftStats = null;
    }
  });
  const hasAudioInputStep = $derived(
    ($update.steps ?? []).some((step) => step.input_type === "audio")
  );
  const wizardMetadata = $derived(getFlowWizardMetadata($update.metadata_json));
  const transcriptionEnabled = $derived(
    typeof wizardMetadata.transcription_enabled === "boolean"
      ? wizardMetadata.transcription_enabled
      : hasAudioInputStep
  );
  const isTranscriptionSkipped = $derived(!transcriptionEnabled);
  const transcriptionModelId = $derived(
    typeof wizardMetadata.transcription_model?.id === "string"
      ? wizardMetadata.transcription_model.id
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
  const transcriptionLanguage = $derived(wizardMetadata.transcription_language ?? "sv");
  const stepsCount = $derived($update.steps?.length ?? 0);
  const checklistHasName = $derived(($update.name ?? "").trim().length > 0);
  const checklistHasSteps = $derived(stepsCount > 0);
  const checklistHasNoErrors = $derived(
    $validationErrors.size === 0 && !hasStepJsonValidationErrors
  );
  const isFlowConfigured = $derived(checklistHasName && checklistHasSteps);
  const checklistEntries = $derived([
    { key: "name", label: m.flow_checklist_name(), done: checklistHasName },
    { key: "steps", label: m.flow_checklist_steps(), done: checklistHasSteps },
    {
      key: "instructions",
      label: m.flow_checklist_instructions(),
      done: checklistHasSteps
    },
    { key: "valid", label: m.flow_checklist_valid(), done: checklistHasNoErrors }
  ]);

  // Auto-select first step when entering stage 4 with no selection
  $effect(() => {
    if (builderStage === 4 && $activeStepId === null && $update.steps.length > 0) {
      flowEditor.selectFirstStepIfUnselected();
    }
  });

  let stageNavigating = $state(false);

  async function navigateToStage(stage: BuilderStageId) {
    if (stage === builderStage || stageNavigating) return;
    stageNavigating = true;
    try {
      await flowEditor.flushSaves();
      builderStage = stage;
    } catch (e) {
      const msg = e instanceof EneoError ? e.getReadableMessage() : String(e);
      toast.error(msg);
    } finally {
      stageNavigating = false;
    }
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
    {activeTab}
    tabs={[
      { value: "builder", label: m.flow_builder() },
      { value: "history", label: m.flow_history() },
      { value: "ai-builder", label: m.ai_builder_tab(), visible: canUseAIBuilder }
    ]}
    tabIdPrefix="flow-detail-tab"
    onTabChange={(v) => {
      if (isFlowPageTab(v)) setActiveTab(v);
    }}
  >
    {#snippet actions()}
      <div class="hidden sm:contents">
        <FlowVersionBadge publishedVersion={$resource.published_version} />
        {#if !$isPublished}
          <FlowSaveStatus status={$saveStatus} />
        {/if}
      </div>
      <div class="hidden lg:contents">
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
          variant="outline"
          disabled={publishLoading}
          onclick={() => {
            unpublishIntent = "edit";
            showUnpublishDialog = true;
          }}
        >
          {#if publishLoading}
            <IconLoadingSpinner data-icon="inline-start" class="animate-spin" />
            {m.flow_unpublish_loading()}
          {:else}
            {m.edit()}
          {/if}
        </Button>
        <Button
          variant="outline"
          disabled={publishLoading}
          onclick={() => {
            unpublishIntent = "service";
            showUnpublishDialog = true;
          }}
        >
          {m.flow_unpublish_confirm_action()}
        </Button>
      {:else}
        <FlowPackageExportDialog
          flow={$resource}
          eneo={data.eneo}
          beforeExport={async () => flowEditor.flushSaves()}
        />
        <Button
          variant={builderStage === 5 ? "default" : "outline"}
          disabled={!canPublish || publishLoading}
          aria-describedby={!canPublish ? "flow-publish-disabled-reason" : undefined}
          title={!canPublish ? m.flow_publish_not_ready_tooltip() : undefined}
          onclick={async () => {
            publishLoading = true;
            try {
              await flowEditor.flushSaves();
              const published = await data.eneo.flows.publish({ id: $resource.id });
              flowEditor.setResource(published);
            } catch (e) {
              const msg = e instanceof EneoError ? e.getReadableMessage() : String(e);
              console.error("Publish failed:", msg);
              toast.error(m.flow_publish_failed({ message: msg }));
              if ($validationErrors.size > 0) {
                validationBannerExpanded = true;
              }
            } finally {
              publishLoading = false;
            }
          }}
        >
          {#if publishLoading}
            <IconLoadingSpinner data-icon="inline-start" class="animate-spin" />
            {m.flow_publish_loading()}
          {:else}
            {m.flow_publish()}
          {/if}
        </Button>
        {#if !canPublish}
          <span id="flow-publish-disabled-reason" class="sr-only">
            {m.flow_publish_disabled_reason()}
          </span>
        {/if}
      {/if}
    {/snippet}
  </FlowPageHeader>

  <Page.Main>
    <div
      id="panel-builder"
      role="tabpanel"
      aria-labelledby="flow-detail-tab-builder"
      hidden={activeTab !== "builder"}
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
      <section
        class="border-default bg-secondary/30 flex flex-col gap-2 border-b px-4 py-3 lg:hidden"
        aria-label={m.flow_user_mode_aria_label()}
      >
        <div class="flex items-center justify-between gap-3">
          <p class="text-primary text-sm font-medium">
            {$userMode === "power_user"
              ? m.flow_mode_power_user_summary()
              : m.flow_mode_user_summary()}
          </p>
          <FlowUserModeToggle />
        </div>
        <p class="text-secondary text-xs leading-relaxed">
          {$userMode === "power_user"
            ? m.flow_power_user_mode_description()
            : m.flow_user_mode_description()}
        </p>
      </section>
      <FlowValidationBanner
        errors={$validationErrors}
        steps={$update.steps}
        onNavigateToStep={(stepId) => {
          builderStage = 4;
          flowEditor.selectStep(stepId);
        }}
        bind:isExpanded={validationBannerExpanded}
      />
      {#if hasStepJsonValidationErrors}
        <Alert.Root
          class="border-warning-default/40 bg-warning-dimmer text-warning-stronger border-b px-4 py-2 text-sm"
          role="alert"
        >
          <CircleAlert class="shrink-0" />
          <Alert.Description class="text-warning-stronger">
            {m.flow_step_json_invalid({ fields: stepJsonValidationSummary })}
          </Alert.Description>
        </Alert.Root>
      {/if}

      <!-- Wizard Stepper -->
      <div class="border-default bg-primary/95 sticky top-0 z-10 border-b backdrop-blur-sm">
        <nav
          class="mx-auto flex max-w-[1600px] items-center gap-2 px-3 py-2.5 sm:px-4 sm:py-3 md:px-6 md:py-3.5"
          aria-label={m.flow_stages_nav_aria()}
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
                  class="mx-1 h-0.5 w-4 shrink-0 transition-colors duration-200 sm:mx-1.5 sm:w-6 xl:mx-3 xl:w-auto xl:flex-1
                    {isPreviousCompleted ? 'bg-accent-default' : 'bg-border-default'}"
                ></div>
              {/if}

              <li class="min-w-0">
                <button
                  type="button"
                  class="hover:bg-hover-dimmer flex min-w-0 items-center gap-1.5 rounded-lg px-1.5 py-1.5 text-sm transition-all duration-200 sm:gap-2 sm:px-2 lg:gap-2.5 lg:px-2.5
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

                  <!-- The current stage keeps its label at every width; other
                       stages show labels only when the full row fits (xl+). -->
                  <span
                    class="{isActive
                      ? 'inline'
                      : 'hidden xl:inline'} truncate text-sm whitespace-nowrap
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
            {/if}
          </div>
        </nav>
      </div>

      <div class="flex flex-1 flex-col overflow-hidden p-4 pt-3">
        {#if builderStage === 1}
          <div class="flex-1 overflow-y-auto px-4 py-5 sm:px-6 md:px-8 md:py-8">
            <div class="mx-auto w-full max-w-6xl">
              <div
                class="grid gap-5 md:gap-6 lg:grid-cols-[minmax(0,1fr)_360px] xl:grid-cols-[minmax(0,1fr)_400px]"
              >
                <Card.Root class="gap-0 py-0">
                  <Card.Header class="px-6 pt-6 pb-0">
                    <Card.Title class="text-base font-semibold tracking-[-0.01em]">
                      {m.flow_basic_settings_title()}
                    </Card.Title>
                    <Card.Description class="text-[0.8125rem] leading-relaxed">
                      {m.flow_basic_settings_desc()}
                    </Card.Description>
                  </Card.Header>
                  <Card.Content class="px-6 pt-5 pb-6">
                    <Field.Group class="gap-5">
                      <Field.Field>
                        <Field.Label for="flow-name-input">{m.flow_flow_name()}</Field.Label>
                        <Input
                          id="flow-name-input"
                          type="text"
                          class="h-10"
                          value={$update.name ?? ""}
                          disabled={$isPublished}
                          oninput={(event) => {
                            flowEditor.setName(event.currentTarget.value);
                          }}
                          placeholder={m.flow_flow_name()}
                        />
                      </Field.Field>
                      <Field.Field>
                        <Field.Label for="flow-description-input">
                          {m.flow_flow_description()}
                        </Field.Label>
                        <Textarea
                          id="flow-description-input"
                          class="min-h-[120px] resize-none py-2.5"
                          value={$update.description ?? ""}
                          disabled={$isPublished}
                          oninput={(event) => {
                            flowEditor.setDescription(event.currentTarget.value);
                          }}
                          placeholder={m.flow_description_placeholder()}
                        />
                      </Field.Field>
                      {#if $userMode === "power_user"}
                        <div
                          class="border-default -mt-1 border-t pt-5"
                          transition:slide={{ duration: 200 }}
                        >
                          <Field.Field>
                            <Field.Label for="flow-retention-input">
                              {m.flow_data_retention_label()}
                            </Field.Label>
                            <div class="border-default bg-secondary rounded-md border px-3 py-2.5">
                              <p class="text-primary text-sm font-medium">
                                {runHistoryRetention.state === "off"
                                  ? m.flow_retention_automatic_off()
                                  : m.flow_retention_effective_days({
                                      days: runHistoryRetention.effective_days
                                    })}
                              </p>
                              <p class="text-secondary mt-1 text-xs leading-relaxed">
                                {m.flow_retention_configured_flow_value({
                                  value:
                                    $update.data_retention_days === null ||
                                    $update.data_retention_days === undefined
                                      ? m.flow_retention_not_configured()
                                      : m.flow_retention_days_value({
                                          days: $update.data_retention_days
                                        })
                                })}
                              </p>
                              <p class="text-secondary mt-1 text-xs leading-relaxed">
                                {m.flow_retention_effective_barriers({
                                  minimum: runHistoryRetention.effective_minimum_days ?? "—",
                                  noPurge: runHistoryRetention.no_purge
                                    ? m.flow_retention_no_purge_on()
                                    : m.flow_retention_no_purge_off()
                                })}
                              </p>
                              {#if runHistoryRetention.policy_conflict}
                                <p class="text-warning-default mt-1 text-xs font-medium">
                                  {m.flow_retention_policy_conflict()}
                                </p>
                              {/if}
                              <dl class="mt-2 grid gap-1 text-xs sm:grid-cols-2">
                                <div>
                                  <dt class="text-secondary font-medium">
                                    {m.flow_retention_activation_sources()}
                                  </dt>
                                  <dd class="text-primary">
                                    {runHistoryRetention.activation_sources
                                      .map(retentionActivationSourceLabel)
                                      .join(", ") || m.flow_retention_source_none()}
                                  </dd>
                                </div>
                                <div>
                                  <dt class="text-secondary font-medium">
                                    {m.flow_retention_barrier_sources()}
                                  </dt>
                                  <dd class="text-primary">
                                    {runHistoryRetention.barrier_sources
                                      .map(retentionBarrierSourceLabel)
                                      .join(", ") || m.flow_retention_source_none()}
                                  </dd>
                                </div>
                              </dl>
                              <dl class="mt-2 grid grid-cols-2 gap-x-4 gap-y-1 text-xs">
                                <div class="flex justify-between gap-2">
                                  <dt class="text-secondary">
                                    {m.flow_retention_contributor_organization()}
                                  </dt>
                                  <dd class="text-primary tabular-nums">
                                    {runHistoryRetention.contributors.organization_days ?? "—"}
                                  </dd>
                                </div>
                                <div class="flex justify-between gap-2">
                                  <dt class="text-secondary">
                                    {m.flow_retention_contributor_organization_minimum()}
                                  </dt>
                                  <dd class="text-primary tabular-nums">
                                    {runHistoryRetention.contributors.organization_minimum_days ??
                                      "—"}
                                  </dd>
                                </div>
                                <div class="flex justify-between gap-2">
                                  <dt class="text-secondary">
                                    {m.flow_retention_contributor_classification_minimum()}
                                  </dt>
                                  <dd class="text-primary tabular-nums">
                                    {runHistoryRetention.contributors.classification_minimum_days ??
                                      "—"}
                                  </dd>
                                </div>
                                <div class="flex justify-between gap-2">
                                  <dt class="text-secondary">
                                    {m.flow_retention_contributor_classification()}
                                  </dt>
                                  <dd class="text-primary tabular-nums">
                                    {runHistoryRetention.contributors.classification_days ?? "—"}
                                  </dd>
                                </div>
                                <div class="flex justify-between gap-2">
                                  <dt class="text-secondary">
                                    {m.flow_retention_contributor_space()}
                                  </dt>
                                  <dd class="text-primary tabular-nums">
                                    {runHistoryRetention.contributors.space_days ?? "—"}
                                  </dd>
                                </div>
                                <div class="flex justify-between gap-2">
                                  <dt class="text-secondary">
                                    {m.flow_retention_contributor_flow()}
                                  </dt>
                                  <dd class="text-primary tabular-nums">
                                    {runHistoryRetention.contributors.flow_days ?? "—"}
                                  </dd>
                                </div>
                              </dl>
                            </div>
                            <div class="flex items-center gap-2.5">
                              <Input
                                id="flow-retention-input"
                                type="number"
                                min="1"
                                max="2555"
                                class="h-10 w-24"
                                value={$update.data_retention_days ?? ""}
                                disabled={!$canEditDataRetentionDays}
                                placeholder="—"
                                oninput={(e) => {
                                  flowEditor.setDataRetentionDaysFromInput(e.currentTarget.value);
                                }}
                              />
                              <span class="text-secondary text-sm"
                                >{m.flow_data_retention_unit()}</span
                              >
                            </div>
                            <Field.Description>
                              {$isPublished
                                ? m.flow_retention_published_read_only()
                                : runHistoryRetention.state === "off"
                                  ? m.flow_retention_off_override_hint()
                                  : m.flow_retention_active_override_hint()}
                            </Field.Description>
                          </Field.Field>
                        </div>
                      {/if}
                    </Field.Group>
                  </Card.Content>
                </Card.Root>
                {#if isFlowConfigured}
                  <Card.Root size="sm" class="gap-0 py-0">
                    <Card.Header class="px-5 pt-5 pb-0">
                      <Card.Title class="text-sm font-semibold tracking-[-0.005em]">
                        {m.flow_summary_title()}
                      </Card.Title>
                      <Card.Description class="text-[0.8125rem]">
                        {m.flow_summary_desc()}
                      </Card.Description>
                    </Card.Header>
                    <Card.Content class="px-5 pt-4 pb-5">
                      <ul
                        class="divide-border divide-y text-sm"
                        style="font-variant-numeric: tabular-nums"
                      >
                        <li class="flex items-center justify-between py-2.5 first:pt-0">
                          <span class="text-secondary">{m.flow_summary_steps()}</span>
                          <span class="text-primary font-semibold">{stepsCount}</span>
                        </li>
                        <li class="flex items-center justify-between py-2.5">
                          <span class="text-secondary">{m.flow_summary_input_fields()}</span>
                          <span class="text-primary font-semibold">{formSchemaFields.length}</span>
                        </li>
                        <li class="flex items-center justify-between py-2.5">
                          <span class="text-secondary">{m.flow_summary_transcription()}</span>
                          <span class="text-primary font-medium">
                            {transcriptionEnabled
                              ? m.flow_transcription_on()
                              : m.flow_transcription_off()}
                          </span>
                        </li>
                        <li class="flex items-center justify-between py-2.5">
                          <span class="text-secondary">{m.flow_summary_validation()}</span>
                          {#if checklistHasNoErrors}
                            <span class="text-positive-stronger inline-flex items-center gap-1.5">
                              <CheckCircle2 class="size-4" />
                            </span>
                          {:else}
                            <span class="text-warning-stronger font-medium">
                              {m.flow_validation_errors_count({
                                count: $validationErrors.size
                              })}
                            </span>
                          {/if}
                        </li>
                        <li class="flex items-center justify-between py-2.5 last:pb-0">
                          <span class="text-secondary">{m.flow_summary_status()}</span>
                          {#if $isPublished}
                            <Badge
                              variant="outline"
                              class="border-positive-default/25 bg-positive-dimmer/50 text-positive-stronger"
                            >
                              {m.flow_status_published_readonly()}
                            </Badge>
                          {:else}
                            <Badge
                              variant="outline"
                              class="border-warning-default/25 bg-warning-dimmer/50 text-warning-stronger"
                            >
                              {m.flow_status_draft()}
                            </Badge>
                          {/if}
                        </li>
                      </ul>
                    </Card.Content>
                  </Card.Root>
                {:else}
                  <Card.Root size="sm" class="gap-0 py-0">
                    <Card.Header class="px-5 pt-5 pb-0">
                      <Card.Title class="text-sm font-semibold tracking-[-0.005em]">
                        {m.flow_checklist_title()}
                      </Card.Title>
                      <Card.Description class="text-[0.8125rem]">
                        {m.flow_checklist_desc()}
                      </Card.Description>
                    </Card.Header>
                    <Card.Content class="px-5 pt-4 pb-5">
                      <ul class="flex flex-col gap-2.5">
                        {#each checklistEntries as item (item.key)}
                          <li class="flex items-center gap-2.5 text-sm">
                            <span
                              class="flex size-5 shrink-0 items-center justify-center rounded-full transition-colors {item.done
                                ? 'bg-positive-dimmer text-positive-stronger'
                                : 'border-default bg-hover-dimmer text-muted border'}"
                              aria-hidden="true"
                            >
                              {#if item.done}
                                <svg
                                  class="size-3"
                                  viewBox="0 0 16 16"
                                  fill="none"
                                  stroke="currentColor"
                                  stroke-width="2.5"
                                  stroke-linecap="round"
                                  stroke-linejoin="round"
                                >
                                  <path d="M3.5 8.5L6.5 11.5L12.5 4.5" />
                                </svg>
                              {/if}
                            </span>
                            <span class={item.done ? "text-primary" : "text-secondary"}>
                              {item.label}
                            </span>
                          </li>
                        {/each}
                      </ul>
                      <div class="mt-5">
                        {#if $isPublished}
                          <Badge
                            variant="outline"
                            class="border-positive-default/25 bg-positive-dimmer/50 text-positive-stronger"
                          >
                            {m.flow_status_published_readonly()}
                          </Badge>
                        {:else}
                          <Badge
                            variant="outline"
                            class="border-warning-default/25 bg-warning-dimmer/50 text-warning-stronger"
                          >
                            {m.flow_status_draft()}
                          </Badge>
                        {/if}
                      </div>
                    </Card.Content>
                  </Card.Root>
                {/if}
              </div>
            </div>
          </div>
        {:else if builderStage === 2}
          <div class="flex-1 overflow-y-auto px-4 py-5 sm:px-6 md:px-8">
            <div class="mx-auto w-full max-w-2xl space-y-4">
              <!-- Main transcription card — single unified card for all states -->
              <Card.Root
                class={[
                  "gap-0 py-0 transition-colors duration-200 ease-out",
                  transcriptionEnabled && "ring-accent-default/25"
                ]}
              >
                <!-- Header: toggle row -->
                <div class="flex items-start justify-between gap-4 px-5 py-4 sm:items-center">
                  <div class="min-w-0 flex-1">
                    <h3 class="text-[0.9375rem] font-semibold tracking-[-0.01em]">
                      {m.flow_transcription_optional_title()}
                    </h3>
                    <p class="text-secondary mt-1 text-[0.8125rem] leading-relaxed">
                      {m.flow_transcription_optional_desc_simple()}
                    </p>
                  </div>
                  <label
                    class="flex shrink-0 cursor-pointer items-center gap-2.5"
                    for="transcription-toggle"
                  >
                    <span class="text-secondary text-sm">
                      {transcriptionEnabled
                        ? m.flow_transcription_on()
                        : m.flow_transcription_off()}
                    </span>
                    <Switch
                      id="transcription-toggle"
                      checked={transcriptionEnabled}
                      disabled={$isPublished}
                      onCheckedChange={(checked) => flowEditor.setTranscriptionEnabled(checked)}
                    />
                  </label>
                </div>

                <!-- Settings: shown when enabled -->
                {#if transcriptionEnabled}
                  <div
                    class="border-default border-t px-5 py-5"
                    transition:slide={{ duration: 200 }}
                  >
                    <Field.Group class="gap-4">
                      <div class="grid gap-4 sm:grid-cols-2">
                        <Field.Field>
                          <Field.Label for="flow-transcription-model">
                            {m.flow_transcription_model_label()}
                          </Field.Label>
                          <SelectAIModelV2
                            bind:selectedModel={transcriptionModel}
                            availableModels={$currentSpace.transcription_models}
                            dropdownLabel={m.flow_transcription_model_label()}
                            on:change={(event) => {
                              const selected = event.detail.selectedModel;
                              const newId = selected?.id ?? null;
                              if (newId !== transcriptionModelId) {
                                flowEditor.setWizardMetadata({
                                  transcription_model: newId ? { id: newId } : null
                                });
                              }
                            }}
                          />
                        </Field.Field>
                        <Field.Field>
                          <Field.Label for="flow-transcription-language">
                            {m.flow_transcription_language_label()}
                          </Field.Label>
                          {@const languageLabel =
                            transcriptionLanguage === "sv"
                              ? "Svenska"
                              : transcriptionLanguage === "en"
                                ? "English"
                                : m.flow_transcription_language_auto()}
                          <Select.Root
                            type="single"
                            value={transcriptionLanguage}
                            disabled={$isPublished}
                            onValueChange={(value) => {
                              if (value)
                                flowEditor.setWizardMetadata({ transcription_language: value });
                            }}
                          >
                            <Select.Trigger id="flow-transcription-language" class="h-10 w-full">
                              {languageLabel}
                            </Select.Trigger>
                            <Select.Content>
                              <!-- eslint-disable-next-line eneo/no-hardcoded-text (language autonym, shown in its own language by convention) -->
                              <Select.Item value="sv" label="Svenska">Svenska</Select.Item>
                              <!-- eslint-disable-next-line eneo/no-hardcoded-text (language autonym, shown in its own language by convention) -->
                              <Select.Item value="en" label="English">English</Select.Item>
                              <Select.Item
                                value="auto"
                                label={m.flow_transcription_language_auto()}
                              >
                                {m.flow_transcription_language_auto()}
                              </Select.Item>
                            </Select.Content>
                          </Select.Root>
                        </Field.Field>
                      </div>
                      {#if transcriptionModelMissingInSpace}
                        <div
                          class="border-warning-default/40 bg-warning-dimmer text-warning-stronger rounded-lg border px-3 py-2 text-sm"
                          role="status"
                        >
                          {m.flow_transcription_model_unavailable_warning()}
                        </div>
                      {/if}
                    </Field.Group>
                  </div>
                {/if}
              </Card.Root>

              <!-- Audio status hint — only when it adds real information -->
              {#if !transcriptionEnabled && hasAudioInputStep}
                <div
                  class="border-warning-default/30 bg-warning-dimmer/50 text-warning-stronger flex items-start gap-3 rounded-xl border px-4 py-3.5 text-sm leading-relaxed"
                  role="status"
                >
                  <svg
                    class="mt-0.5 size-4 shrink-0"
                    viewBox="0 0 16 16"
                    fill="currentColor"
                    aria-hidden="true"
                  >
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
              class="border-default bg-primary max-h-[42vh] w-full overflow-hidden rounded-xl border shadow-sm sm:max-h-[48vh] lg:max-h-none lg:w-80 lg:shrink-0 xl:w-[340px]"
            >
              <FlowStepList
                steps={$update.steps}
                activeStepId={$activeStepId}
                isPublished={$isPublished}
                validationErrors={$validationErrors}
                onBuildWithAI={canUseAIBuilder
                  ? () => {
                      ensureAIBuilder();
                      setActiveTab("ai-builder");
                    }
                  : undefined}
                onSelectStep={async (stepId) => {
                  try {
                    await flowEditor.flushSaves();
                  } catch (error) {
                    const message =
                      error instanceof EneoError
                        ? error.getReadableMessage()
                        : "Kunde inte spara stegets ändringar.";
                    toast.error(message);
                  }
                  if (stepId) {
                    flowEditor.selectStep(stepId);
                  }
                }}
                onMoveStep={async (index, direction) => {
                  try {
                    await flowEditor.moveStepAtIndex(index, direction);
                  } catch (error) {
                    const message =
                      error instanceof EneoError
                        ? error.getReadableMessage()
                        : "Kunde inte uppdatera stegordning.";
                    toast.error(message);
                  }
                }}
                onRemoveStep={async (index) => {
                  try {
                    await flowEditor.removeStepAtIndex(index);
                  } catch (error) {
                    const message =
                      error instanceof EneoError
                        ? error.getReadableMessage()
                        : "Kunde inte ta bort steget.";
                    toast.error(message);
                  }
                }}
              />
            </div>

            <div
              class="border-default bg-primary flex-1 overflow-hidden rounded-xl border shadow-sm lg:max-w-[900px] 2xl:max-w-[1000px]"
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
                  formSchema={formSchemaMetadata}
                  onOpenTranscriptionSettings={() => void navigateToStage(2)}
                  onJsonValidationChanged={(detail) => {
                    hasStepJsonValidationErrors = detail.hasErrors;
                    stepJsonValidationFields = detail.fields;
                  }}
                  onStepChanged={(detail) => {
                    const { index, step } = detail;
                    flowEditor.replaceStepAtIndex(index, step);
                  }}
                />
              </div>
            </div>
          </div>

          <FlowGraphPanel
            flow={$update}
            activeStepId={$activeStepId}
            onNodeClick={(stepId) => flowEditor.selectStep(stepId)}
          />
        {:else}
          <div class="flex-1 overflow-y-auto p-4 sm:p-5 md:p-8">
            <div class="mx-auto w-full max-w-6xl space-y-5 md:space-y-6">
              <!-- Pipeline summary -->
              <section
                class="border-default bg-primary rounded-2xl border p-5 shadow-sm sm:p-6"
                aria-labelledby="flow-review-pipeline-heading"
              >
                <div class="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                  <h3
                    id="flow-review-pipeline-heading"
                    class="text-[0.9375rem] font-semibold tracking-[-0.005em]"
                  >
                    {m.flow_review_pipeline_title()}
                  </h3>
                  <span
                    class="text-muted text-xs font-semibold tracking-[0.06em] uppercase tabular-nums"
                  >
                    {($update.steps ?? []).length}&nbsp;&middot;&nbsp;{m.flow_steps()}
                  </span>
                </div>
                <div class="mt-5 flex flex-wrap items-center gap-2.5 sm:gap-3">
                  <div
                    class="bg-accent-dimmer text-accent-stronger rounded-xl px-3.5 py-2 text-[13px] font-medium tracking-[-0.005em]"
                  >
                    {m.flow_review_input_label()}
                  </div>
                  {#each $update.steps ?? [] as pipeStep, stepIdx (pipeStep.id ?? pipeStep.step_order)}
                    <span class="text-muted text-base" aria-hidden="true">&rarr;</span>
                    {@const completionModel =
                      "completion_model" in pipeStep
                        ? (pipeStep as { completion_model?: { name?: string | null } | null })
                            .completion_model
                        : null}
                    <div
                      class="border-default/80 bg-secondary/20 hover:bg-secondary/35 flex min-w-0 items-center gap-2 rounded-xl border px-3 py-2 transition-colors"
                    >
                      <span
                        class="bg-hover-dimmer text-secondary flex size-5 shrink-0 items-center justify-center rounded-md text-xs font-semibold tabular-nums"
                        aria-hidden="true"
                      >
                        {stepIdx + 1}
                      </span>
                      <div class="flex min-w-0 flex-col">
                        <span
                          class="text-primary max-w-[14rem] truncate text-[13px] leading-snug font-medium"
                          title={pipeStep.user_description ||
                            m.flow_step_fallback_label({
                              order: String(pipeStep.step_order)
                            })}
                        >
                          {pipeStep.user_description ||
                            m.flow_step_fallback_label({ order: String(pipeStep.step_order) })}
                        </span>
                        {#if completionModel?.name}
                          <span
                            class="text-muted max-w-[14rem] truncate text-xs leading-snug tabular-nums"
                            title={completionModel.name}
                          >
                            {completionModel.name}
                          </span>
                        {/if}
                      </div>
                    </div>
                  {/each}
                  <span class="text-muted text-base" aria-hidden="true">&rarr;</span>
                  <div
                    class="bg-positive-dimmer text-positive-stronger rounded-xl px-3.5 py-2 text-[13px] font-medium tracking-[-0.005em]"
                  >
                    {m.flow_review_output_label()}
                  </div>
                </div>
              </section>

              <!-- Test section -->
              <section
                class="border-default bg-primary rounded-2xl border p-5 shadow-sm sm:p-6"
                aria-labelledby="flow-review-testing-heading"
              >
                <div class="flex flex-wrap items-start justify-between gap-x-4 gap-y-2">
                  <div class="min-w-0 flex-1">
                    <h4
                      id="flow-review-testing-heading"
                      class="text-[0.9375rem] font-semibold tracking-[-0.005em]"
                    >
                      {m.flow_testing()}
                    </h4>
                    {#if $isPublished && $userMode === "power_user"}
                      <p class="text-secondary mt-1 text-sm leading-relaxed">
                        {m.flow_export_debug_desc()}
                      </p>
                    {:else if !$isPublished}
                      <p class="text-secondary mt-1 text-sm leading-relaxed">
                        {m.flow_dry_run_desc()}
                      </p>
                    {/if}
                  </div>
                  {#if !$isPublished}
                    {#if $validationErrors.size === 0 && !hasStepJsonValidationErrors}
                      <span
                        class="border-positive-default/30 bg-positive-dimmer/70 text-positive-stronger inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold tracking-[0.015em]"
                        role="status"
                      >
                        <CheckCircle2 class="size-3" aria-hidden="true" />
                        {m.flow_publish_status_ready()}
                      </span>
                    {:else}
                      <span
                        class="border-warning-default/30 bg-warning-dimmer/70 text-warning-stronger inline-flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-semibold tracking-[0.015em] tabular-nums"
                      >
                        {m.flow_validation_errors_count({
                          count: $validationErrors.size + (hasStepJsonValidationErrors ? 1 : 0)
                        })}
                      </span>
                    {/if}
                  {/if}
                </div>

                <div class="mt-5 flex flex-col gap-3">
                  {#if $isPublished}
                    <div class="flex flex-wrap items-center gap-2">
                      <Button
                        variant="default"
                        size="default"
                        class="h-9 gap-2"
                        onclick={() => (showRunDialog = true)}
                      >
                        {m.flow_run_trigger()}
                      </Button>
                      <Button variant="outline" class="h-9" onclick={() => setActiveTab("history")}>
                        {m.flow_show_history()}
                      </Button>
                    </div>
                  {:else}
                    <div class="flex flex-wrap items-center gap-2">
                      <FlowDryRun flow={$resource} />
                      <Button variant="outline" class="h-9" onclick={() => setActiveTab("history")}>
                        {m.flow_show_history()}
                      </Button>
                    </div>
                  {/if}
                </div>
              </section>
            </div>
          </div>
        {/if}
      </div>
    </div>

    {#if canUseAIBuilder && aiBuilderInitialized}
      <div
        id="panel-ai-builder"
        role="tabpanel"
        aria-labelledby="flow-detail-tab-ai-builder"
        hidden={activeTab !== "ai-builder"}
        class="flex min-h-0 flex-1 flex-col overflow-hidden"
        class:hidden={activeTab !== "ai-builder"}
      >
        <FlowAIBuilderEditHost
          eneo={data.eneo}
          spaceId={$currentSpace.id}
          flowId={$resource.id}
          onapplied={async (detail) => {
            try {
              const updated = await data.eneo.flows.get({ id: detail.flow_id });
              flowEditor.setResource(updated);
              const navigation = resolveAIBuilderApplyNavigation({
                stepCount: updated.steps?.length ?? 0,
                requestedFocusStepIndex: detail.focusStepIndex
              });
              setActiveTab(navigation.activeTab);
              builderStage = navigation.builderStage;
              const focusedStepId = resolveApplyFocusedStepId(
                updated.steps ?? [],
                navigation.focusStepIndex
              );
              if (focusedStepId) {
                flowEditor.selectStep(focusedStepId);
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
      aria-labelledby="flow-detail-tab-history"
      hidden={activeTab !== "history"}
      class="flex-1 overflow-y-auto"
      class:hidden={activeTab !== "history"}
    >
      <FlowRunsTable
        flow={$resource}
        {careDataPolicy}
        eneo={data.eneo}
        visible={activeTab === "history"}
        optimisticRuns={optimisticHistoryRuns}
        reloadTrigger={runsReloadTrigger}
        bind:latestRunPayload={latestHistoryPayload}
        onOptimisticRunsConfirmed={(runIds) => {
          const confirmedIds = new Set(runIds);
          optimisticHistoryRuns = optimisticHistoryRuns.filter((run) => !confirmedIds.has(run.id));
        }}
      />
    </div>
  </Page.Main>
</Page.Root>

<FlowRunDialog
  bind:open={showRunDialog}
  flow={$resource}
  {careDataPolicy}
  eneo={data.eneo}
  lastInputPayload={latestHistoryPayload}
  onRunCreated={(detail) => {
    optimisticHistoryRuns = [
      detail.run,
      ...optimisticHistoryRuns.filter((run) => run.id !== detail.run.id)
    ];
    setActiveTab("history");
    runsReloadTrigger++;
  }}
/>

<AlertDialog.Root bind:open={showUnpublishDialog}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>
        {unpublishIntent === "edit"
          ? m.flow_unpublish_confirm_title()
          : m.flow_unpublish_service_confirm_title()}
      </AlertDialog.Title>
      <AlertDialog.Description>{m.flow_unpublish_confirm_body()}</AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        variant="destructive"
        onclick={async () => {
          showUnpublishDialog = false;
          publishLoading = true;
          try {
            const updated = await data.eneo.flows.unpublish({ id: $resource.id });
            flowEditor.setResource(updated);
          } catch (e) {
            const msg = e instanceof EneoError ? e.getReadableMessage() : String(e);
            console.error("Unpublish failed:", msg);
            toast.error(m.flow_unpublish_failed({ message: msg }));
          } finally {
            publishLoading = false;
          }
        }}
      >
        {unpublishIntent === "edit"
          ? m.flow_unpublish_and_edit_action()
          : m.flow_unpublish_confirm_action()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>

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
