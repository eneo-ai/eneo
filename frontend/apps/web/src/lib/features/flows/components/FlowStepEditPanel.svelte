<script lang="ts">
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import FlowStepChapter from "$lib/features/flows/components/FlowStepChapter.svelte";
  import {
    EneoError,
    type FlowStep,
    type SecurityClassification,
    type UploadedFile
  } from "@eneo/eneo-js";
  import { Settings } from "$lib/components/layout";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getEneo } from "$lib/core/Eneo";
  import { initAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import { writable } from "svelte/store";
  import { onDestroy, tick } from "svelte";
  import { IconWorkflow } from "@eneo/icons/workflow";
  import { IconChevronRight } from "@eneo/icons/chevron-right";
  import MousePointerClick from "lucide-svelte/icons/mouse-pointer-click";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import {
    getAvailableOutputModes,
    getAvailableOutputTypes,
    getOutputModeCompatibilityIssue,
    getFlowStepValidationIssues,
    getSelectableInputSourceOptions,
    getSelectableInputTypeOptions,
    outputModeUsesCompletionModel
  } from "$lib/features/flows/flowStepTypes";
  import {
    needsTranscribeOnlyOutputModeReset,
    needsTranscribeOnlyOutputTypeCoercion,
    shouldAutoClearLegacyTemplate
  } from "$lib/features/flows/flowStepEditorGuards";
  import {
    getOutputHintKind,
    getSourceHintKind,
    getStepSummaryModel,
    sortSelectableInputTypeOptionsForDisplay
  } from "$lib/features/flows/flowStepPresentation";
  import { buildNextFlowPrompt } from "$lib/features/flows/flowPromptDraft";
  import {
    applyAutoTemplateBindings,
    getTemplateFillOutputConfig,
    isTemplateFillStep,
    updateTemplateBinding
  } from "$lib/features/flows/templateFillConfig";
  import { shouldShowTemplateBodyTextHint } from "$lib/features/flows/templateFillAuthoringHints";
  import {
    buildRuntimeInputStepPatch,
    getRuntimeInputConfig,
    type FlowRuntimeInputConfigValue
  } from "$lib/features/flows/flowRuntimeInputConfig";
  import { getFlowStepUxCopy } from "$lib/features/flows/flowStepUxCopy";
  import {
    collectTemplateStepReferenceOrders,
    getInputTemplateSourceConflictStepOrders
  } from "$lib/features/flows/flowVariableTokens";
  import {
    getInputBindingQuestion,
    hasInputBindingSourceRefs,
    setInputBindingQuestion,
    setInputBindingSourceRefs,
    type FlowInputBindingSourceRef
  } from "$lib/features/flows/flowInputBindings";
  import {
    applyInputSourceChange,
    applyInputTypeChange,
    applyOutputModeChange,
    applyOutputTypeChange
  } from "$lib/features/flows/flowStepTransitionPolicy";
  import {
    preserveFlowCitationMode,
    setFlowCitationMode,
    type FlowCitationMode
  } from "$lib/features/flows/flowCitationMode";
  import {
    buildFlowStepReviewPolicyPatch,
    type FlowStepReviewModeChoice
  } from "$lib/features/flows/flowStepReviewPolicy";

  // Extracted state management
  import { FlowStepAssistantState } from "./FlowStepAssistantState.svelte.ts";
  import { FlowTemplateState } from "./FlowTemplateState.svelte.ts";

  // Extracted helpers
  import { getInputTypeLabel, getInputSourceLabel, getIssueMessage } from "./flowStepEditHelpers";
  import {
    getDefaultOpenStepChapter,
    getStepAiWork
  } from "$lib/features/flows/flowStepEditorPresentation";
  import {
    getChapterInputStatus,
    getChapterTaskStatus,
    getChapterOutputStatus,
    getChapterControlStatus,
    getChapterAdvancedStatus,
    getTechnicalSettingsCount
  } from "./flowStepChapterStatus";
  import {
    type AdvancedJsonField,
    getStepKeyForAdvancedJson,
    syncDraftsFromStep,
    syncDraftsFromStepValues,
    clearHiddenFieldErrors,
    parseAdvancedJsonField,
    formatAdvancedJsonDraftField,
    getErrorFields,
    type AdvancedJsonDrafts,
    type AdvancedJsonErrors
  } from "./advancedJsonDrafts";

  // Sub-components
  import FlowStepSummaryCard from "./FlowStepSummaryCard.svelte";
  import FlowStepInputSection from "./FlowStepInputSection.svelte";
  import FlowStepBehaviorSection from "./FlowStepBehaviorSection.svelte";
  import FlowStepContextSection from "./FlowStepContextSection.svelte";
  import FlowStepInputTemplateSection from "./FlowStepInputTemplateSection.svelte";
  import FlowStepTemplateFillSection from "./FlowStepTemplateFillSection.svelte";
  import FlowStepSpeakerMappingSection from "./FlowStepSpeakerMappingSection.svelte";
  import {
    buildSpeakerMappingOutputConfig,
    getSpeakerMappingParticipantsField
  } from "$lib/features/flows/speakerMappingConfig";
  import FlowStepOutputSection from "./FlowStepOutputSection.svelte";
  import FlowStepTypedIoBanners from "./FlowStepTypedIoBanners.svelte";
  import FlowStepReviewSection from "./FlowStepReviewSection.svelte";
  import FlowStepSecuritySection from "./FlowStepSecuritySection.svelte";
  import FlowStepAdvancedSection from "./FlowStepAdvancedSection.svelte";

  // ---------------------------------------------------------------------------
  // Props
  // ---------------------------------------------------------------------------

  let {
    steps,
    activeStepId,
    isPublished,
    securityClassifications = [],
    transcriptionEnabled = true,
    transcriptionModelConfigured = false,
    transcriptionModelLabel = null,
    formSchema,
    onStepChanged,
    onJsonValidationChanged,
    onOpenTranscriptionSettings,
    speakerMappingStepOffered = false,
    onAddSpeakerMappingStep,
    onBuildFlowWithAI,
    onEditStepWithAI
  }: {
    steps: FlowStep[];
    activeStepId: string | null;
    isPublished: boolean;
    securityClassifications?: SecurityClassification[];
    transcriptionEnabled?: boolean;
    transcriptionModelConfigured?: boolean;
    transcriptionModelLabel?: string | null;
    formSchema?:
      | {
          fields: {
            name: string;
            type: string;
            required?: boolean;
            options?: string[];
            order?: number;
          }[];
        }
      | undefined;
    onStepChanged?: (detail: { index: number; step: FlowStep }) => void;
    onJsonValidationChanged?: (detail: { hasErrors: boolean; fields: string[] }) => void;
    onOpenTranscriptionSettings?: () => void;
    /** Diarization is on and no step after this one names the speakers yet. */
    speakerMappingStepOffered?: boolean;
    onAddSpeakerMappingStep?: () => void;
    onBuildFlowWithAI?: () => void;
    onEditStepWithAI?: (step: FlowStep) => void;
  } = $props();

  // ---------------------------------------------------------------------------
  // Context & services
  // ---------------------------------------------------------------------------

  const mode = getFlowUserMode();
  const flowEditor = getFlowEditor();
  const assistantReloadRevision = flowEditor.assistantReloadRevision;
  const flowResource = flowEditor.state.resource;
  const currentFlowId = $derived($flowResource?.id ?? "");
  const {
    state: { currentSpace }
  } = getSpacesManager();
  const eneo = getEneo();
  const attachmentRules = writable({});
  const {
    state: { attachments: newAttachments },
    clearUploads
  } = initAttachmentManager({
    eneo,
    options: {
      rules: attachmentRules,
      onFileUploaded: (newFile: UploadedFile) => assistantState.onFileUploaded(newFile)
    }
  });

  const assistantState = new FlowStepAssistantState({
    flowEditor,
    eneo,
    attachmentRules,
    newAttachments,
    clearUploads,
    getActiveStep: () => activeStep
  });

  const templateState = new FlowTemplateState({ eneo, flowEditor });

  // ---------------------------------------------------------------------------
  // Core derived state
  // ---------------------------------------------------------------------------

  const activeIndex = $derived(steps.findIndex((s) => s.id === activeStepId));
  const activeStep = $derived(activeIndex >= 0 ? steps[activeIndex] : null);
  const activeStepStateKey = $derived(
    activeStep?.id ?? (activeStep ? `draft:${activeStep.step_order}` : "no-step")
  );
  const isAdvancedMode = $derived($mode === "power_user");
  const orderedStepsForNav = $derived([...steps].sort((a, b) => a.step_order - b.step_order));
  const activeStepNavIndex = $derived(
    activeStep ? orderedStepsForNav.findIndex((step) => step.id === activeStep.id) : -1
  );
  const previousStepForNav = $derived(
    activeStepNavIndex > 0 ? orderedStepsForNav[activeStepNavIndex - 1] : null
  );
  const nextStepForNav = $derived(
    activeStepNavIndex >= 0 && activeStepNavIndex < orderedStepsForNav.length - 1
      ? orderedStepsForNav[activeStepNavIndex + 1]
      : null
  );

  const httpVariableContext = $derived(
    activeStep
      ? {
          steps,
          currentStepOrder: activeStep.step_order,
          formSchema,
          isAdvancedMode,
          transcriptionEnabled
        }
      : undefined
  );
  const locale = (getLocale() === "en" ? "en" : "sv") as "sv" | "en";
  const hasAudioInputSteps = $derived(steps.some((step) => step.input_type === "audio"));

  // ---------------------------------------------------------------------------
  // Input feedback state
  // ---------------------------------------------------------------------------

  let inputSourceFeedback: string | null = $state(null);
  let inputTypeFeedback: string | null = $state(null);
  let lastFeedbackStepKey: string | null = $state(null);

  $effect(() => {
    const nextKey = activeStep ? `${activeStep.id ?? "new"}:${activeStep.step_order}` : null;
    if (nextKey !== lastFeedbackStepKey) {
      lastFeedbackStepKey = nextKey;
      inputSourceFeedback = null;
      inputTypeFeedback = null;
      revealInputTemplateInUserMode = false;
    }
  });

  // ---------------------------------------------------------------------------
  // Advanced JSON drafts (uses extracted reducer functions)
  // ---------------------------------------------------------------------------

  let advancedJsonDraftStepKey: string | null = $state(null);
  let advancedJsonDrafts: AdvancedJsonDrafts = $state({
    input_contract: "",
    output_contract: "",
    input_config: "",
    output_config: ""
  });
  let advancedJsonErrors: AdvancedJsonErrors = $state({});

  function emitAdvancedJsonValidationState() {
    const fields = getErrorFields(advancedJsonErrors);
    onJsonValidationChanged?.({ hasErrors: fields.length > 0, fields });
  }

  $effect(() => {
    const nextStepKey = getStepKeyForAdvancedJson(activeStep);
    if (nextStepKey !== advancedJsonDraftStepKey) {
      advancedJsonDraftStepKey = nextStepKey;
      const synced = syncDraftsFromStep(activeStep);
      advancedJsonDrafts = synced.drafts;
      advancedJsonErrors = synced.errors;
      emitAdvancedJsonValidationState();
    }
  });

  $effect(() => {
    if (activeStep !== null) {
      const updated = syncDraftsFromStepValues(advancedJsonDrafts, advancedJsonErrors, activeStep);
      if (updated) {
        advancedJsonDrafts = updated;
      }
    }
  });

  $effect(() => {
    if (activeStep !== null) {
      const cleaned = clearHiddenFieldErrors(advancedJsonErrors, activeStep);
      if (cleaned) {
        advancedJsonErrors = cleaned;
        emitAdvancedJsonValidationState();
      }
    }
  });

  function handleAdvancedJsonFieldUpdate(field: AdvancedJsonField, rawValue: string) {
    const result = parseAdvancedJsonField(advancedJsonDrafts, advancedJsonErrors, field, rawValue);
    advancedJsonDrafts = result.drafts;
    advancedJsonErrors = result.errors;
    emitAdvancedJsonValidationState();
    if (result.parseError === null) {
      updateStep(field, result.parsed);
    }
  }

  function handleAdvancedJsonFieldFormat(field: AdvancedJsonField) {
    const result = formatAdvancedJsonDraftField(advancedJsonDrafts, advancedJsonErrors, field);
    advancedJsonDrafts = result.drafts;
    advancedJsonErrors = result.errors;
    emitAdvancedJsonValidationState();
    if (result.parseError === null) {
      updateStep(field, result.parsed);
    }
  }

  // ---------------------------------------------------------------------------
  // Assistant & template state (delegated to extracted classes)
  // ---------------------------------------------------------------------------

  let stepNameBeforeEdit = $state("");

  $effect(() => {
    assistantState.syncWithActiveStep(activeStep, $assistantReloadRevision);
  });
  $effect(() => {
    return () => {
      assistantState.destroy();
    };
  });
  $effect(() => {
    assistantState.syncAttachmentRules();
  });

  // ---------------------------------------------------------------------------
  // Step mutation helpers
  // ---------------------------------------------------------------------------

  function updateStep(field: string, value: unknown) {
    if (activeStep === null || activeIndex < 0) return;
    const updated = { ...activeStep, [field]: value };
    onStepChanged?.({ index: activeIndex, step: updated });
    if (field === "user_description" && activeStep.assistant_id) {
      flowEditor.saveAssistant(activeStep.assistant_id, { name: value });
    }
  }

  function updateStepPatch(patch: Partial<FlowStep>) {
    if (activeStep === null || activeIndex < 0) return;
    onStepChanged?.({ index: activeIndex, step: { ...activeStep, ...patch } });
  }

  function updateAssistantField(field: string, value: unknown) {
    assistantState.updateField(field, value);
  }

  // ---------------------------------------------------------------------------
  // Instruction & input template
  // ---------------------------------------------------------------------------

  async function updateInstruction(value: string) {
    if (!activeStep?.assistant_id || !assistantState.assistant) return;
    const nextPrompt = buildNextFlowPrompt(assistantState.assistant.prompt, value);
    assistantState.updateField("prompt", nextPrompt);
    await flowEditor.updateAssistantImmediately(activeStep.assistant_id, { prompt: nextPrompt });
  }

  function queueInstructionDraft(value: string) {
    if (!activeStep?.assistant_id || !assistantState.assistant) return;
    const nextPrompt = buildNextFlowPrompt(assistantState.assistant.prompt, value);
    assistantState.updateField("prompt", nextPrompt);
    void flowEditor.saveAssistant(activeStep.assistant_id, { prompt: nextPrompt }).catch(() => {});
  }

  function updateInputTemplate(value: string) {
    if (activeStep === null) return;
    const result = setInputBindingQuestion(activeStep.input_bindings, value);
    if (result.status === "blocked") return;
    updateStep("input_bindings", result.inputBindings);
  }

  function updateInputSources(sourceRefs: FlowInputBindingSourceRef[]) {
    if (activeStep === null) return;
    const result = setInputBindingSourceRefs(activeStep.input_bindings, sourceRefs);
    if (result.status === "blocked") return;
    updateStep("input_bindings", result.inputBindings);
  }

  async function handleCommittedStepRename() {
    if (!activeStep) return;
    const oldName = stepNameBeforeEdit.trim();
    const newName = (activeStep.user_description ?? "").trim();
    if (!oldName || !newName || oldName === newName) return;
    try {
      await flowEditor.rewriteStepNameVariableReferences({
        renamedStepOrder: activeStep.step_order,
        oldName,
        newName
      });
    } catch (error) {
      const message =
        error instanceof EneoError
          ? error.getReadableMessage()
          : m.flow_step_rename_rewrite_failed();
      toast.error(message);
    }
  }

  // ---------------------------------------------------------------------------
  // Transition policy handlers
  // ---------------------------------------------------------------------------

  function handleInputSourceChange(nextSource: FlowStep["input_source"]) {
    if (activeStep === null || activeIndex < 0) return;
    inputSourceFeedback = null;
    inputTypeFeedback = null;
    const result = applyInputSourceChange({
      step: activeStep,
      nextSource,
      previousOutputType: nextSource === "previous_step" ? previousStep?.output_type : undefined,
      runtimeInputConfig,
      isAdvancedMode
    });
    if (result.inputTypeAdjusted) {
      inputTypeFeedback = m.flow_step_input_type_adjusted({
        inputType: getInputTypeLabel(result.step.input_type)
      });
    }
    onStepChanged?.({ index: activeIndex, step: result.step });
  }

  function handleInputTypeChange(nextType: FlowStep["input_type"]) {
    if (activeStep === null || activeIndex < 0) return;
    inputSourceFeedback = null;
    inputTypeFeedback = null;
    const result = applyInputTypeChange({
      step: activeStep,
      nextType,
      runtimeInputConfig
    });
    if (result.inputSourceAdjusted) {
      inputSourceFeedback = m.flow_step_input_source_adjusted({
        inputSource: getInputSourceLabel(result.step.input_source)
      });
    }
    onStepChanged?.({ index: activeIndex, step: result.step });
  }

  function handleOutputModeChange(nextMode: FlowStep["output_mode"]) {
    if (activeStep === null || activeIndex < 0) return;
    onStepChanged?.({
      index: activeIndex,
      step: applyOutputModeChange({
        step: activeStep,
        nextMode,
        runtimeInputConfig,
        templateFillConfig
      })
    });
  }

  function handleOutputTypeChange(nextType: FlowStep["output_type"]) {
    if (activeStep === null || activeIndex < 0) return;
    onStepChanged?.({
      index: activeIndex,
      step: applyOutputTypeChange({ step: activeStep, nextType })
    });
  }

  function updateRuntimeInputSettings(
    patch:
      | Partial<FlowRuntimeInputConfigValue>
      | ((current: FlowRuntimeInputConfigValue) => FlowRuntimeInputConfigValue)
  ) {
    if (!activeStep) return;
    const nextConfig =
      typeof patch === "function" ? patch(runtimeInputConfig) : { ...runtimeInputConfig, ...patch };
    updateStepPatch(buildRuntimeInputStepPatch(activeStep, nextConfig));
  }

  function handleCitationModeChange(nextCitationMode: FlowCitationMode) {
    if (!activeStep) return;
    updateStep("output_config", setFlowCitationMode(activeStep.output_config, nextCitationMode));
  }

  function handleReviewModeChange(nextReviewMode: FlowStepReviewModeChoice) {
    updateStepPatch(buildFlowStepReviewPolicyPatch(nextReviewMode));
  }

  // ---------------------------------------------------------------------------
  // Template fill handlers (delegated to templateState)
  // ---------------------------------------------------------------------------

  function templateContext() {
    return { activeStep: activeStep!, steps, formSchema, updateStep };
  }

  function applyAllTemplateSuggestions() {
    updateStep(
      "output_config",
      applyAutoTemplateBindings({
        currentConfig: templateFillConfig,
        autoSuggestions: templateAutoBindings,
        placeholders: templatePlaceholders.map((item) => item.name)
      })
    );
  }

  function handleTemplateBindingChange(placeholder: string, value: string) {
    if (value === "__unset__") {
      const nextBindings = { ...(templateFillConfig.bindings ?? {}) };
      delete nextBindings[placeholder];
      updateStep("output_config", { ...templateFillConfig, bindings: nextBindings });
      return;
    }
    updateStep("output_config", updateTemplateBinding(templateFillConfig, placeholder, value));
  }

  // ---------------------------------------------------------------------------
  // Derived values for sub-components
  // ---------------------------------------------------------------------------

  const previousStep = $derived(
    activeStep && activeStep.step_order > 1
      ? steps.find((s) => s.step_order === activeStep!.step_order - 1)
      : null
  );
  const hasKnowledgeSelections = $derived(
    Boolean(
      assistantState.assistant &&
      ((Array.isArray(assistantState.assistant.websites) &&
        assistantState.assistant.websites.length > 0) ||
        (Array.isArray(assistantState.assistant.groups) &&
          assistantState.assistant.groups.length > 0) ||
        (Array.isArray(assistantState.assistant.integration_knowledge_list) &&
          assistantState.assistant.integration_knowledge_list.length > 0))
    )
  );
  const hasAttachmentSelections = $derived(
    Boolean(
      assistantState.assistant &&
      Array.isArray(assistantState.assistant.attachments) &&
      assistantState.assistant.attachments.length > 0
    )
  );
  const currentStepIssues = $derived(
    activeStep
      ? getFlowStepValidationIssues(steps).filter(
          (issue) => issue.stepOrder === activeStep.step_order
        )
      : []
  );
  const sourceValidationIssue = $derived(
    currentStepIssues.find((issue) => issue.field === "input_source") ?? null
  );
  const inputTypeValidationIssue = $derived(
    currentStepIssues.find((issue) => issue.field === "input_type") ?? null
  );
  const sourceValidationMessage = $derived(
    getIssueMessage(sourceValidationIssue, activeStep, previousStep)
  );
  const inputTypeValidationMessage = $derived(
    getIssueMessage(inputTypeValidationIssue, activeStep, previousStep)
  );

  const selectableInputSourceOptions = $derived(
    activeStep
      ? getSelectableInputSourceOptions({
          steps,
          stepOrder: activeStep.step_order,
          currentInputSource: activeStep.input_source,
          isAdvancedMode
        })
      : []
  );
  const selectableInputTypeOptions = $derived(
    activeStep
      ? getSelectableInputTypeOptions({
          inputSource: activeStep.input_source,
          previousOutputType: previousStep?.output_type,
          currentInputType: activeStep.input_type,
          isAdvancedMode
        })
      : []
  );
  const displayedInputTypeOptions = $derived(
    activeStep
      ? sortSelectableInputTypeOptionsForDisplay({
          options: selectableInputTypeOptions,
          inputSource: activeStep.input_source,
          previousOutputType: previousStep?.output_type
        })
      : []
  );
  const sourceHintKind = $derived(
    activeStep
      ? getSourceHintKind({
          inputSource: activeStep.input_source,
          previousOutputType: previousStep?.output_type
        })
      : null
  );
  const outputHintKind = $derived(activeStep ? getOutputHintKind(activeStep.output_type) : null);

  const isTemplateFill = $derived(isTemplateFillStep(activeStep));
  const templateFillConfig = $derived(getTemplateFillOutputConfig(activeStep));
  const templateDerived = $derived(templateState.getDerived(activeStep, steps, formSchema));
  const templatePlaceholders = $derived(templateDerived.placeholders);
  const templateBindingSuggestionGroups = $derived(templateDerived.suggestionGroups);
  const templateAutoBindings = $derived(templateDerived.autoBindings);
  const templateBindingRows = $derived(templateDerived.bindingRows);
  const templateReadiness = $derived(templateDerived.readiness);
  const templateOrphanedRows = $derived(templateDerived.orphanedRows);
  const templateHasSelection = $derived(templateDerived.hasSelection);
  const resolvedTemplateAssetId = $derived(templateDerived.resolvedAssetId);
  const selectedTemplateAsset = $derived(templateDerived.selectedAsset);
  const templateUnnamedStepWarning = $derived(templateDerived.unnamedStepWarning);
  const templateAutoMatchableCount = $derived(templateDerived.autoMatchableCount);
  const runtimeInputConfig = $derived(
    activeStep
      ? getRuntimeInputConfig(activeStep)
      : ({
          enabled: false,
          required: false,
          max_files: null,
          input_format: "document",
          accepted_mimetypes_override: [],
          label: "",
          description: ""
        } satisfies FlowRuntimeInputConfigValue)
  );

  // Output type/mode options
  const availableOutputTypes = $derived(getAvailableOutputTypes(activeStep));
  const availableOutputModes = $derived(
    getAvailableOutputModes({ step: activeStep, isAdvancedMode })
  );
  const isTranscribeOnly = $derived(activeStep?.output_mode === "transcribe_only");

  // Instruction & input template derived
  const instructionText = $derived(
    assistantState.assistant &&
      typeof assistantState.assistant === "object" &&
      assistantState.assistant.prompt &&
      typeof assistantState.assistant.prompt === "object"
      ? (assistantState.assistant.prompt.text ?? "")
      : ""
  );
  // Chapter presentation: one source drives the collapsed status lines and
  // which chapter opens by default (the one needing attention).
  const aiInstructionPresent = $derived(
    assistantState.assistant ? instructionText.trim().length > 0 : null
  );
  const stepAiWork = $derived(
    activeStep ? getStepAiWork(activeStep, { instructionPresent: aiInstructionPresent }) : null
  );
  const outputCompatibilityIssue = $derived(
    activeStep ? getOutputModeCompatibilityIssue(activeStep) : null
  );
  // The first open section follows the step's task. Per-step interaction state
  // is retained by FlowStepChapter for the current page session.
  const newStepOpenIntent = flowEditor.state.newStepOpenIntent;
  const defaultOpenChapter = $derived.by(() => {
    if (!activeStep) return null;
    const intent = $newStepOpenIntent;
    if (intent && intent.stepId === activeStep.id) return "task";
    return getDefaultOpenStepChapter({
      step: activeStep,
      hasInputError: currentStepIssues.length > 0,
      hasOutputError: outputCompatibilityIssue !== null
    });
  });
  let taskRequestOpen = $state(0);
  let technicalRequestOpen = $state(0);
  let focusInstructionPending = $state(false);
  // A step the user just added lands with its name selected, so typing renames
  // it at once. The editor owns the "once": taking the focus marks the intent
  // handed over there, so neither the temp→real id reconciliation nor a later
  // mount of this panel can steal focus a second time.
  let nameInputEl = $state<HTMLInputElement | null>(null);
  $effect(() => {
    const intent = $newStepOpenIntent;
    const el = nameInputEl;
    const step = activeStep;
    if (!intent?.focusPending || !step || !el || intent.stepId !== step.id) return;
    flowEditor.takeNewStepFocus(intent.token);
    el.focus();
    el.select();
  });
  // Leaving the step editor ends the creation episode: coming back should open
  // the chapter the step's own state calls for, not the one it was created on.
  onDestroy(() => flowEditor.clearNewStepOpenIntent());
  const chapterTaskStatus = $derived(
    activeStep
      ? getChapterTaskStatus(
          activeStep,
          instructionText,
          stepAiWork?.text ?? activeStep.user_description ?? ""
        )
      : ""
  );
  const chapterInputStatus = $derived(
    activeStep
      ? getChapterInputStatus({
          step: activeStep,
          previousStep,
          hasKnowledge: hasKnowledgeSelections,
          hasAttachments: hasAttachmentSelections
        })
      : ""
  );
  const chapterOutputStatus = $derived(
    activeStep ? getChapterOutputStatus(activeStep, isAdvancedMode) : ""
  );
  const chapterControlStatus = $derived(
    activeStep
      ? getChapterControlStatus(
          activeStep,
          $currentSpace.security_classification,
          securityClassifications
        )
      : ""
  );
  const chapterAdvancedStatus = $derived(
    activeStep ? getChapterAdvancedStatus(activeStep) : m.flow_chapter_advanced_default()
  );
  const technicalSettingsCount = $derived(activeStep ? getTechnicalSettingsCount(activeStep) : 0);
  const inputTemplateText = $derived(
    activeStep ? getInputBindingQuestion(activeStep.input_bindings) : ""
  );
  const hasInputTemplateOverride = $derived(inputTemplateText.trim().length > 0);
  const hasTypedInputSources = $derived(
    activeStep ? hasInputBindingSourceRefs(activeStep.input_bindings) : false
  );
  const stepSummaryModel = $derived(
    activeStep
      ? getStepSummaryModel({
          step: activeStep,
          previousStep,
          hasInputTemplateOverride: hasInputTemplateOverride || hasTypedInputSources,
          hasKnowledge: hasKnowledgeSelections,
          hasAttachments: hasAttachmentSelections
        })
      : null
  );
  let revealInputTemplateInUserMode = $state(false);
  const canRevealInputTemplate = $derived(
    !isTranscribeOnly && activeStep !== null && !isAdvancedMode
  );
  const showInputTemplate = $derived(
    isAdvancedMode ||
      hasInputTemplateOverride ||
      (canRevealInputTemplate && revealInputTemplateInUserMode)
  );
  const stepUxCopy = $derived(getFlowStepUxCopy({ locale, inputSource: activeStep?.input_source }));
  const inputTemplateSectionTitle = $derived(stepUxCopy.inputTemplateTitle);
  const inputTemplateSectionDescription = $derived(stepUxCopy.inputTemplateDescription);

  async function showTechnicalSettings() {
    mode.set("power_user");
    await tick();
    technicalRequestOpen += 1;
  }

  const templateStepRefs = $derived.by(() => {
    return collectTemplateStepReferenceOrders(inputTemplateText);
  });

  const templateSourceConflict = $derived.by(() => {
    if (!activeStep || templateStepRefs.length === 0) return null;
    return getInputTemplateSourceConflictStepOrders({
      inputSource: activeStep.input_source,
      stepOrder: activeStep.step_order,
      templateStepRefs
    });
  });

  // ---------------------------------------------------------------------------
  // Template inspection reactive triggers (delegated to templateState)
  // ---------------------------------------------------------------------------

  $effect(() => {
    const assetToInspect = templateState.syncInspection(
      activeStep,
      isTemplateFill,
      resolvedTemplateAssetId
    );
    if (assetToInspect && activeStep) {
      void templateState.inspectFile(
        assetToInspect,
        { persist: false },
        {
          activeStep,
          steps,
          formSchema,
          updateStep
        }
      );
    }
  });

  $effect(() => {
    if (
      isAdvancedMode &&
      isTemplateFill &&
      !templateState.filesLoaded &&
      !templateState.filesLoading
    ) {
      void templateState.loadFiles();
    }
  });

  // ---------------------------------------------------------------------------
  // Guard reactive blocks
  // ---------------------------------------------------------------------------

  // Legacy cleanup: old builder versions could accidentally mirror instruction -> input template.
  $effect(() => {
    if (
      activeStep?.id &&
      shouldAutoClearLegacyTemplate({
        stepId: activeStep.id,
        isPublished,
        hasInputTemplateOverride,
        instructionText,
        inputTemplateText,
        alreadyAutoCleared: assistantState.autoClearedLegacyTemplateByStepId.has(activeStep.id)
      })
    ) {
      assistantState.autoClearedLegacyTemplateByStepId.add(activeStep.id);
      updateInputTemplate("");
    }
  });

  $effect(() => {
    if (activeStep && activeIndex >= 0 && needsTranscribeOnlyOutputTypeCoercion(activeStep)) {
      updateStep("output_type", "text");
    }
  });

  $effect(() => {
    if (activeStep && activeIndex >= 0 && needsTranscribeOnlyOutputModeReset(activeStep)) {
      updateStep("output_mode", "pass_through");
    }
  });
</script>

{#if activeStep === null}
  {#if steps.length === 0}
    <div class="flex h-full flex-col items-center justify-center gap-5 px-8 text-center">
      <div class="bg-hover-dimmer flex size-16 items-center justify-center rounded-2xl shadow-sm">
        <IconWorkflow class="text-secondary size-8" />
      </div>
      <div class="flex flex-col gap-2">
        <h2 class="text-lg font-semibold">{m.flow_no_steps_welcome_title()}</h2>
        <p class="text-secondary max-w-md text-sm leading-relaxed">
          {m.flow_no_steps_welcome_description()}
        </p>
      </div>
      {#if !isPublished}
        <div class="flex max-w-xl flex-col items-center gap-3">
          <div class="flex flex-wrap items-center justify-center gap-2">
            <Button onclick={() => flowEditor.addStep()}>
              {m.flow_empty_add_step()}
            </Button>
            <Button variant="outline" onclick={() => flowEditor.createDraftingChainStarter()}>
              {m.flow_starter_drafting_action()}
            </Button>
            {#if onBuildFlowWithAI}
              <Button variant="outline" onclick={onBuildFlowWithAI}>
                {m.ai_builder_empty_state_cta()}
              </Button>
            {/if}
          </div>
          <p class="text-muted max-w-lg text-xs leading-relaxed">
            {m.flow_starter_drafting_body()}
          </p>
        </div>
      {/if}
    </div>
  {:else}
    <div class="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
      <MousePointerClick class="text-muted/40 mb-3 size-10" />
      <h2 class="text-lg font-semibold">{m.flow_step_select_prompt()}</h2>
      <p class="text-secondary max-w-md text-sm">
        {m.flow_step_select_prompt_desc()}
      </p>
    </div>
  {/if}
{:else}
  <div class="p-4 pb-8 sm:p-5 sm:pb-8 lg:p-6 lg:pb-10">
    <div class="flow-step-editor">
      <div class="flow-step-editor-content mx-auto w-full max-w-[1000px]">
        <div class="mb-4 flex min-w-0 items-start justify-between gap-4">
          <div class="min-w-0">
            <span class="flex items-center gap-1">
              <span class="text-secondary block text-xs font-medium tracking-[0.02em]">
                {m.flow_step_position({
                  index: String(activeStep.step_order),
                  total: String(steps.length)
                })}
              </span>
              {#if steps.length > 1}
                <Button
                  variant="ghost"
                  size="icon"
                  class="size-6"
                  disabled={!previousStepForNav}
                  aria-label={m.flow_step_go_previous()}
                  onclick={() =>
                    previousStepForNav?.id && flowEditor.selectStep(previousStepForNav.id)}
                >
                  <IconChevronRight class="size-3.5 rotate-180" />
                </Button>
                <Button
                  variant="ghost"
                  size="icon"
                  class="size-6"
                  disabled={!nextStepForNav}
                  aria-label={m.flow_step_go_next()}
                  onclick={() => nextStepForNav?.id && flowEditor.selectStep(nextStepForNav.id)}
                >
                  <IconChevronRight class="size-3.5" />
                </Button>
              {/if}
            </span>
            {#if activeStep.user_description}
              <h2 class="text-primary mt-1 truncate text-lg font-semibold tracking-[-0.02em]">
                {activeStep.user_description}
              </h2>
            {/if}
          </div>
          {#if onEditStepWithAI && activeStep.id && !isPublished}
            <Button variant="outline" size="sm" onclick={() => onEditStepWithAI?.(activeStep)}>
              {m.flow_step_change_with_ai()}
            </Button>
          {/if}
        </div>
        {#if stepSummaryModel}
          <FlowStepSummaryCard
            step={activeStep}
            summaryModel={stepSummaryModel}
            {previousStep}
            {isAdvancedMode}
            {aiInstructionPresent}
            onFixInstruction={() => {
              taskRequestOpen++;
              focusInstructionPending = true;
            }}
          />
          <Separator class="my-2" />
        {/if}

        <FlowStepChapter
          title={m.flow_chapter_what()}
          status={chapterTaskStatus}
          initialOpen={defaultOpenChapter === "task"}
          resetKey={activeStepStateKey}
          requestOpen={taskRequestOpen}
        >
          <FlowStepSection>
            <Settings.Row
              title={m.flow_step_name()}
              description=""
              help={m.flow_step_name_help()}
              density="compact"
              let:aria
            >
              <div class="flex flex-col gap-2">
                <Input
                  {...aria}
                  bind:ref={nameInputEl}
                  value={activeStep.user_description ?? ""}
                  placeholder={m.flow_step_name_placeholder()}
                  disabled={isPublished}
                  onfocus={() => {
                    stepNameBeforeEdit = activeStep.user_description ?? "";
                  }}
                  oninput={(e) => updateStep("user_description", e.currentTarget.value || null)}
                  onchange={() => void handleCommittedStepRename()}
                />
                {#if shouldShowTemplateBodyTextHint( { steps, activeStep, isTemplateFill, isTranscribeOnly } )}
                  <p
                    class="bg-accent-dimmer/30 text-accent-stronger rounded-lg px-3 py-2 text-xs leading-relaxed"
                  >
                    {m.flow_template_fill_step_name_hint()}
                  </p>
                {/if}
              </div>
            </Settings.Row>
          </FlowStepSection>

          {#if !isTemplateFill && !isTranscribeOnly && outputModeUsesCompletionModel(activeStep.output_mode)}
            <FlowStepBehaviorSection
              step={activeStep}
              {isPublished}
              {isAdvancedMode}
              {isTranscribeOnly}
              instructionMissing={stepAiWork?.missing ?? false}
              focusInstruction={focusInstructionPending}
              onInstructionFocused={() => (focusInstructionPending = false)}
              assistant={assistantState.assistant}
              assistantLoading={assistantState.loading}
              promptGuideAvailability={assistantState.promptGuideAvailability}
              availableModels={$currentSpace.completion_models}
              {steps}
              {formSchema}
              {transcriptionEnabled}
              {hasAudioInputSteps}
              {stepUxCopy}
              {instructionText}
              loadPromptVersions={(id) => flowEditor.listAssistantPrompts(id)}
              onAssistantFieldChange={(detail) => updateAssistantField(detail.field, detail.value)}
              onInstructionDraft={(detail) => queueInstructionDraft(detail.value)}
              onInstructionCommit={(detail) => void updateInstruction(detail.value)}
              onPreparePromptGuide={async () => {
                try {
                  await flowEditor.flushAssistantSaves();
                  return true;
                } catch {
                  return false;
                }
              }}
            />
          {/if}
        </FlowStepChapter>

        <FlowStepChapter
          title={m.flow_chapter_input()}
          status={chapterInputStatus}
          initialOpen={defaultOpenChapter === "input"}
          resetKey={activeStepStateKey}
        >
          <FlowStepInputSection
            step={activeStep}
            {isPublished}
            {isAdvancedMode}
            {httpVariableContext}
            {selectableInputSourceOptions}
            {displayedInputTypeOptions}
            {runtimeInputConfig}
            {sourceHintKind}
            {sourceValidationMessage}
            {inputSourceFeedback}
            {inputTypeValidationMessage}
            {inputTypeFeedback}
            {transcriptionEnabled}
            {transcriptionModelConfigured}
            {transcriptionModelLabel}
            flowId={currentFlowId}
            onInputSourceChange={(detail) =>
              handleInputSourceChange(detail.value as FlowStep["input_source"])}
            onInputTypeChange={(detail) =>
              handleInputTypeChange(detail.value as FlowStep["input_type"])}
            onRuntimeInputChange={(detail) => updateRuntimeInputSettings(detail.patch)}
            onHttpConfigChange={(detail) => updateStep("input_config", detail.config)}
            onOpenTranscriptionSettings={() => onOpenTranscriptionSettings?.()}
            {speakerMappingStepOffered}
            onAddSpeakerMappingStep={() => onAddSpeakerMappingStep?.()}
          />

          {#if isTranscribeOnly}
            <FlowStepBehaviorSection
              step={activeStep}
              {isPublished}
              {isAdvancedMode}
              {isTranscribeOnly}
              instructionMissing={stepAiWork?.missing ?? false}
              focusInstruction={focusInstructionPending}
              onInstructionFocused={() => (focusInstructionPending = false)}
              assistant={assistantState.assistant}
              assistantLoading={assistantState.loading}
              promptGuideAvailability={assistantState.promptGuideAvailability}
              availableModels={$currentSpace.completion_models}
              {steps}
              {formSchema}
              {transcriptionEnabled}
              {hasAudioInputSteps}
              {stepUxCopy}
              {instructionText}
              loadPromptVersions={(id) => flowEditor.listAssistantPrompts(id)}
              onAssistantFieldChange={(detail) => updateAssistantField(detail.field, detail.value)}
              onInstructionDraft={(detail) => queueInstructionDraft(detail.value)}
              onInstructionCommit={(detail) => void updateInstruction(detail.value)}
              onPreparePromptGuide={async () => {
                try {
                  await flowEditor.flushAssistantSaves();
                  return true;
                } catch {
                  return false;
                }
              }}
            />
          {/if}

          {#if !isTranscribeOnly && !isTemplateFill}
            <FlowStepContextSection
              resetKey={activeStepStateKey}
              {isPublished}
              assistant={assistantState.assistant}
              assistantLoading={assistantState.loading}
              runningUploads={assistantState.runningUploads}
              onKnowledgeChange={(detail) => {
                updateAssistantField("websites", detail.websites);
                updateAssistantField("groups", detail.groups);
                updateAssistantField("integration_knowledge_list", detail.integrationKnowledgeList);
              }}
              onRemoveAttachment={(detail) => void assistantState.removeAttachment(detail.file)}
            />
          {/if}

          {#if !isTranscribeOnly && !isTemplateFill}
            <FlowStepInputTemplateSection
              resetKey={activeStepStateKey}
              step={activeStep}
              {isPublished}
              {isAdvancedMode}
              isPowerUser={$mode === "power_user"}
              {hasInputTemplateOverride}
              {showInputTemplate}
              {inputTemplateText}
              {templateSourceConflict}
              {templateStepRefs}
              {steps}
              {formSchema}
              {transcriptionEnabled}
              {hasAudioInputSteps}
              runtimeInputEnabled={runtimeInputConfig.enabled}
              {stepUxCopy}
              {inputTemplateSectionTitle}
              {inputTemplateSectionDescription}
              onRevealInputTemplate={() => (revealInputTemplateInUserMode = true)}
              onClearInputTemplate={() => updateInputTemplate("")}
              onInputTemplateChange={(detail) => updateInputTemplate(detail.value)}
              onInputSourcesChange={(detail) => updateInputSources(detail.sourceRefs)}
              onInputSourceChange={(detail) =>
                handleInputSourceChange(detail.value as FlowStep["input_source"])}
            />
          {/if}
        </FlowStepChapter>

        <FlowStepChapter
          title={m.flow_chapter_output()}
          status={chapterOutputStatus}
          initialOpen={defaultOpenChapter === "result"}
          resetKey={activeStepStateKey}
        >
          {#if isTemplateFill}
            <FlowStepTemplateFillSection
              {isPublished}
              {isAdvancedMode}
              {templateFillConfig}
              templateInspection={templateState.inspection}
              templateInspecting={templateState.inspecting}
              templateConfigError={templateState.configError}
              templateFilesLoading={templateState.filesLoading}
              {templatePlaceholders}
              {templateBindingRows}
              {templateBindingSuggestionGroups}
              {templateAutoBindings}
              {templateReadiness}
              {templateOrphanedRows}
              {templateHasSelection}
              {resolvedTemplateAssetId}
              {selectedTemplateAsset}
              {templateUnnamedStepWarning}
              {templateAutoMatchableCount}
              availableTemplateFiles={templateState.availableFiles}
              onOutputModeChange={(detail) =>
                handleOutputModeChange(detail.value as FlowStep["output_mode"])}
              onTemplateFileSelect={(detail) =>
                void templateState.handleFileSelection(detail.assetId, templateContext())}
              onTemplateUpload={(detail) =>
                void templateState.handleUpload(detail.event, templateContext())}
              onTemplateDownload={() =>
                resolvedTemplateAssetId && void templateState.download(resolvedTemplateAssetId)}
              onTemplateRefresh={() =>
                resolvedTemplateAssetId &&
                void templateState.inspectFile(
                  resolvedTemplateAssetId,
                  { persist: false },
                  templateContext()
                )}
              onBindingChange={(detail) =>
                handleTemplateBindingChange(detail.placeholder, detail.value)}
              onApplyAllSuggestions={applyAllTemplateSuggestions}
            />
          {:else}
            <FlowStepOutputSection
              embedded
              step={activeStep}
              {isPublished}
              {isAdvancedMode}
              {httpVariableContext}
              {availableOutputTypes}
              {availableOutputModes}
              {outputHintKind}
              flowId={currentFlowId}
              onOutputTypeChange={(detail) =>
                handleOutputTypeChange(detail.value as FlowStep["output_type"])}
              onOutputModeChange={(detail) =>
                handleOutputModeChange(detail.value as FlowStep["output_mode"])}
              onWebhookUrlChange={(detail) =>
                updateStep("output_config", {
                  ...(activeStep?.output_config ?? {}),
                  url: detail.value
                })}
              onHttpConfigChange={(detail) =>
                updateStep(
                  "output_config",
                  preserveFlowCitationMode(
                    detail.config as unknown as Record<string, unknown>,
                    activeStep?.output_config ?? null
                  )
                )}
              onCitationModeChange={(detail) => handleCitationModeChange(detail.value)}
              onSwitchToTemplateFill={() => handleOutputModeChange("template_fill")}
            />
            {#if activeStep.output_mode === "speaker_mapping"}
              <FlowStepSpeakerMappingSection
                step={activeStep}
                {isPublished}
                formFields={formSchema?.fields ?? []}
                onParticipantsFieldChange={(detail) =>
                  updateStep(
                    "output_config",
                    buildSpeakerMappingOutputConfig(activeStep?.output_config ?? null, detail.value)
                  )}
                onSpeakerCountFieldChange={(detail) =>
                  updateStep(
                    "output_config",
                    buildSpeakerMappingOutputConfig(
                      activeStep?.output_config ?? null,
                      getSpeakerMappingParticipantsField(activeStep),
                      detail.value
                    )
                  )}
              />
            {/if}
          {/if}
        </FlowStepChapter>

        <FlowStepChapter
          title={m.flow_chapter_control()}
          status={chapterControlStatus}
          initialOpen={defaultOpenChapter === "control"}
          resetKey={activeStepStateKey}
        >
          <div class="grid gap-6 lg:grid-cols-2 lg:gap-8">
            <FlowStepReviewSection
              step={activeStep}
              {isPublished}
              onReviewModeChange={(detail) => handleReviewModeChange(detail.value)}
            />

            <FlowStepSecuritySection
              step={activeStep}
              {isPublished}
              classifications={securityClassifications}
              inheritedClassification={$currentSpace.security_classification}
              onClassificationChange={(detail) =>
                updateStep("output_classification_override", detail.value)}
            />
          </div>
        </FlowStepChapter>

        {#if isAdvancedMode && !isTemplateFill}
          <FlowStepChapter
            title={m.flow_chapter_technical()}
            status={chapterAdvancedStatus}
            initialOpen={defaultOpenChapter === "technical"}
            resetKey={activeStepStateKey}
            requestOpen={technicalRequestOpen}
          >
            <FlowStepTypedIoBanners step={activeStep} />
            <FlowStepAdvancedSection
              embedded
              step={activeStep}
              {isPublished}
              {advancedJsonDrafts}
              {advancedJsonErrors}
              onJsonFieldUpdate={(detail) =>
                handleAdvancedJsonFieldUpdate(detail.field, detail.value)}
              onJsonFieldFormat={(detail) => handleAdvancedJsonFieldFormat(detail.field)}
            />
          </FlowStepChapter>
        {:else if !isAdvancedMode && technicalSettingsCount > 0}
          <div class="flex flex-wrap items-center gap-x-5 gap-y-2 px-2 py-4">
            <p class="text-secondary text-[0.8125rem]">
              {technicalSettingsCount === 1
                ? m.flow_technical_settings_count_one()
                : m.flow_technical_settings_count_many({ count: technicalSettingsCount })}
            </p>
            <Button variant="link" size="sm" class="h-auto px-0" onclick={showTechnicalSettings}>
              {m.flow_show_in_advanced()}
            </Button>
          </div>
        {/if}
      </div>
    </div>
  </div>
{/if}

<style>
  @media (min-width: 2400px) {
    .flow-step-editor-content {
      max-width: 1280px;
    }
  }
</style>
