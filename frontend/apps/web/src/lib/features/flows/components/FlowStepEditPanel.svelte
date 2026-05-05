<script lang="ts">
  import { IntricError, type FlowStep, type UploadedFile } from "@intric/intric-js";
  import { Settings } from "$lib/components/layout";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getIntric } from "$lib/core/Intric";
  import { initAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import { SvelteMap, SvelteSet } from "svelte/reactivity";
  import { writable } from "svelte/store";
  import { IconWorkflow } from "@intric/icons/workflow";
  import { MousePointerClick } from "lucide-svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import {
    getFlowStepValidationIssues,
    getSelectableInputSourceOptions,
    getSelectableInputTypeOptions
  } from "$lib/features/flows/flowStepTypes";
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

  // Extracted state management
  import { FlowStepAssistantState } from "./FlowStepAssistantState.svelte.ts";
  import { FlowTemplateState } from "./FlowTemplateState.svelte.ts";

  // Extracted helpers
  import {
    getInputTypeLabel,
    getInputSourceLabel,
    getIssueMessage,
    OUTPUT_TYPES,
    OUTPUT_MODES
  } from "./flowStepEditHelpers";
  import {
    type AdvancedJsonField,
    getStepKeyForAdvancedJson,
    syncDraftsFromStep,
    syncDraftsFromStepValues,
    clearHiddenFieldErrors,
    parseAdvancedJsonField,
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
  import FlowStepOutputSection from "./FlowStepOutputSection.svelte";
  import FlowStepSecuritySection from "./FlowStepSecuritySection.svelte";
  import FlowStepAdvancedSection from "./FlowStepAdvancedSection.svelte";
  import FlowStepDeleteSection from "./FlowStepDeleteSection.svelte";
  import SelectMCPServers from "$lib/features/mcp/components/SelectMCPServers.svelte";
  import {
    buildFlowStepMcpCompatibilityMap,
    hasLoadedFlowStepMcpClassificationInputs,
    shouldShowStepMcpSection,
    summarizeAssistantMcp
  } from "$lib/features/flows/flowStepMcpConfig";

  // ---------------------------------------------------------------------------
  // Props
  // ---------------------------------------------------------------------------

  let {
    steps,
    activeStepId,
    isPublished,
    transcriptionEnabled = true,
    transcriptionModelConfigured = false,
    transcriptionModelLabel = null,
    formSchema,
    onStepChanged,
    onRemoveStep,
    onJsonValidationChanged,
    onOpenTranscriptionSettings
  }: {
    steps: FlowStep[];
    activeStepId: string | null;
    isPublished: boolean;
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
    onRemoveStep?: (index: number) => void;
    onJsonValidationChanged?: (detail: { hasErrors: boolean; fields: string[] }) => void;
    onOpenTranscriptionSettings?: () => void;
  } = $props();

  // ---------------------------------------------------------------------------
  // Context & services
  // ---------------------------------------------------------------------------

  const mode = getFlowUserMode();
  const flowEditor = getFlowEditor();
  const assistantRevision = flowEditor.assistantRevision;
  const flowResource = flowEditor.state.resource;
  const currentFlowId = $derived($flowResource?.id ?? "");
  const {
    state: { currentSpace }
  } = getSpacesManager();
  const intric = getIntric();
  const attachmentRules = writable({});
  const {
    state: { attachments: newAttachments },
    clearUploads
  } = initAttachmentManager({
    intric,
    options: {
      rules: attachmentRules,
      onFileUploaded: (newFile: UploadedFile) => assistantState.onFileUploaded(newFile)
    }
  });

  const assistantState = new FlowStepAssistantState({
    flowEditor,
    intric,
    attachmentRules,
    newAttachments,
    clearUploads,
    getActiveStep: () => activeStep
  });

  const templateState = new FlowTemplateState({ intric, flowEditor });
  let assistantsById = new SvelteMap<string, unknown>();
  let lastLoadedRevisionByAssistant = new SvelteMap<string, number>();
  const loadingAssistantIds = new SvelteSet<string>();

  // ---------------------------------------------------------------------------
  // Core derived state
  // ---------------------------------------------------------------------------

  const activeIndex = $derived(steps.findIndex((s) => s.id === activeStepId));
  const activeStep = $derived(activeIndex >= 0 ? steps[activeIndex] : null);
  const isAdvancedMode = $derived($mode === "power_user");
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

  // ---------------------------------------------------------------------------
  // Assistant & template state (delegated to extracted classes)
  // ---------------------------------------------------------------------------

  let stepNameBeforeEdit = $state("");

  $effect(() => {
    assistantState.syncWithActiveStep(activeStep);
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
    const nextBindings: Record<string, unknown> = {
      ...((activeStep.input_bindings as Record<string, unknown> | null) ?? {})
    };
    delete nextBindings.text;
    if (value.trim().length === 0) {
      delete nextBindings.question;
    } else {
      nextBindings.question = value;
    }
    updateStep("input_bindings", Object.keys(nextBindings).length > 0 ? nextBindings : null);
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
        error instanceof IntricError
          ? error.getReadableMessage()
          : "Failed to rewrite downstream variable references.";
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
  const mcpSummary = $derived(summarizeAssistantMcp(assistantState.assistant));
  const hasActiveMcp = $derived(mcpSummary.hasActiveMcp);
  const showMcpSection = $derived(shouldShowStepMcpSection(activeStep?.output_mode));
  const knowledgeDisabledByMcp = $derived(hasActiveMcp && !hasKnowledgeSelections);
  const mcpDisabledByKnowledge = $derived(hasKnowledgeSelections && !hasActiveMcp);
  const flowMcpCompatibilityById = $derived.by(() => {
    if (!activeStep || !showMcpSection) {
      return {};
    }
    const compatibilityMap = buildFlowStepMcpCompatibilityMap({
      step: activeStep,
      steps,
      assistantsById,
      availableServers: ($currentSpace.mcp_servers ?? []) as Array<{
        id: string;
        security_classification?: { security_level?: number; name?: string } | null;
      }>,
      spaceSecurityClassification: $currentSpace.security_classification
    });
    return Object.fromEntries(
      Object.entries(compatibilityMap).map(([serverId, compatibility]) => [
        serverId,
        {
          ...compatibility,
          reason: compatibility.isCompatible
            ? undefined
            : m.flow_step_mcp_server_does_not_meet_security_classification()
        }
      ])
    );
  });
  const mcpCompatibilityReady = $derived(
    hasLoadedFlowStepMcpClassificationInputs({
      step: activeStep,
      steps,
      assistantsById
    })
  );

  $effect(() => {
    const revision = $assistantRevision;
    if (!showMcpSection) return;

    if (assistantState.assistant && activeStep?.assistant_id) {
      assistantsById.set(activeStep.assistant_id, assistantState.assistant);
      lastLoadedRevisionByAssistant.set(activeStep.assistant_id, revision);
    }

    const assistantIds = steps
      .map((step) => step.assistant_id)
      .filter(
        (assistantId): assistantId is string =>
          typeof assistantId === "string" && assistantId.length > 0
      );

    for (const assistantId of assistantIds) {
      if (
        lastLoadedRevisionByAssistant.get(assistantId) === revision ||
        loadingAssistantIds.has(assistantId)
      ) {
        continue;
      }
      loadingAssistantIds.add(assistantId);
      void flowEditor
        .loadAssistant(assistantId)
        .then((assistant) => {
          assistantsById.set(assistantId, assistant);
          lastLoadedRevisionByAssistant.set(assistantId, revision);
        })
        .finally(() => {
          loadingAssistantIds.delete(assistantId);
        });
    }
  });
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
          currentInputSource: activeStep.input_source
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
  const availableOutputTypes = $derived(
    activeStep?.output_mode === "transcribe_only"
      ? OUTPUT_TYPES.filter((type) => type.value === "text")
      : activeStep?.output_mode === "template_fill"
        ? OUTPUT_TYPES.filter((type) => type.value === "docx")
        : OUTPUT_TYPES
  );
  const availableOutputModes = $derived.by(() => {
    const base =
      activeStep?.input_type === "audio"
        ? OUTPUT_MODES
        : OUTPUT_MODES.filter((mode) => mode.value !== "transcribe_only");
    const visible =
      isAdvancedMode || activeStep?.output_mode === "template_fill"
        ? base
        : base.filter((mode) => mode.value !== "template_fill");
    return visible;
  });
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
  const inputTemplateText = $derived(
    activeStep && activeStep.input_bindings && typeof activeStep.input_bindings === "object"
      ? ((activeStep.input_bindings.question as string) ?? "")
      : ""
  );
  const hasInputTemplateOverride = $derived(inputTemplateText.trim().length > 0);
  const stepSummaryModel = $derived(
    activeStep
      ? getStepSummaryModel({
          step: activeStep,
          previousStep,
          hasInputTemplateOverride,
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
    isAdvancedMode || (canRevealInputTemplate && revealInputTemplateInUserMode)
  );
  const stepUxCopy = $derived(getFlowStepUxCopy({ locale, inputSource: activeStep?.input_source }));
  const inputTemplateSectionTitle = $derived(stepUxCopy.inputTemplateTitle);
  const inputTemplateSectionDescription = $derived(stepUxCopy.inputTemplateDescription);

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
      !isPublished &&
      hasInputTemplateOverride &&
      instructionText.trim().length > 0 &&
      inputTemplateText.trim() === instructionText.trim() &&
      !assistantState.autoClearedLegacyTemplateByStepId.has(activeStep.id)
    ) {
      assistantState.autoClearedLegacyTemplateByStepId.add(activeStep.id);
      updateInputTemplate("");
    }
  });

  $effect(() => {
    if (
      activeStep &&
      activeIndex >= 0 &&
      activeStep.output_mode === "transcribe_only" &&
      activeStep.output_type !== "text"
    ) {
      updateStep("output_type", "text");
    }
  });

  $effect(() => {
    if (
      activeStep &&
      activeIndex >= 0 &&
      activeStep.input_type !== "audio" &&
      activeStep.output_mode === "transcribe_only"
    ) {
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
        <h3 class="text-lg font-semibold">{m.flow_no_steps_welcome_title()}</h3>
        <p class="text-secondary max-w-md text-sm leading-relaxed">
          {m.flow_no_steps_welcome_description()}
        </p>
      </div>
      {#if !isPublished}
        <Button onclick={() => flowEditor.addStep()}>
          {m.flow_empty_add_step()}
        </Button>
      {/if}
    </div>
  {:else}
    <div class="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
      <MousePointerClick class="text-muted/40 mb-3 size-10" />
      <h3 class="text-lg font-semibold">{m.flow_step_select_prompt()}</h3>
      <p class="text-secondary max-w-md text-sm">
        {m.flow_step_select_prompt_desc()}
      </p>
    </div>
  {/if}
{:else}
  <div
    class="p-4 pb-8 sm:p-5 sm:pb-8 lg:p-6 lg:pb-10"
    class:pointer-events-none={isPublished}
    class:opacity-60={isPublished}
  >
    <div
      class="flow-step-editor [&_section>div:last-child]:gap-6 [&_section>div:last-child]:pb-6 [&_section>h2]:font-sans [&_section>h2]:text-[11px] [&_section>h2]:font-semibold [&_section>h2]:tracking-[0.06em] [&_section>h2]:uppercase"
    >
      <Settings.Page>
        {#if stepSummaryModel}
          <FlowStepSummaryCard
            step={activeStep}
            summaryModel={stepSummaryModel}
            {previousStep}
            {isAdvancedMode}
            {hasInputTemplateOverride}
          />
          <Separator class="my-2" />
        {/if}

        <Settings.Group title={m.flow_step_section_details()}>
          <Settings.Row title={m.flow_step_name()} description="" let:aria>
            <div class="flex flex-col gap-2">
              <input
                {...aria}
                class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
                value={activeStep.user_description ?? ""}
                placeholder={m.flow_step_name_placeholder()}
                disabled={isPublished}
                onfocus={() => {
                  stepNameBeforeEdit = activeStep.user_description ?? "";
                }}
                oninput={(e) => updateStep("user_description", e.currentTarget.value || null)}
                onchange={() => void handleCommittedStepRename()}
              />
              {#if shouldShowTemplateBodyTextHint( { steps, activeStep, isAdvancedMode, isTemplateFill, isTranscribeOnly } )}
                <p
                  class="bg-accent-dimmer/30 text-accent-stronger rounded-lg px-3 py-2 text-xs leading-relaxed"
                >
                  {m.flow_template_fill_step_name_hint()}
                </p>
              {/if}
            </div>
          </Settings.Row>
        </Settings.Group>

        {#if !isTemplateFill}
          <FlowStepInputSection
            step={activeStep}
            {isPublished}
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
          />
        {/if}

        {#if !isTemplateFill}
          <FlowStepBehaviorSection
            step={activeStep}
            {isPublished}
            {isAdvancedMode}
            {isTranscribeOnly}
            assistant={assistantState.assistant}
            assistantLoading={assistantState.loading}
            availableModels={$currentSpace.completion_models}
            {steps}
            {formSchema}
            {transcriptionEnabled}
            {hasAudioInputSteps}
            {stepUxCopy}
            {instructionText}
            {canRevealInputTemplate}
            {showInputTemplate}
            loadPromptVersions={(id) => flowEditor.listAssistantPrompts(id)}
            onAssistantFieldChange={(detail) => updateAssistantField(detail.field, detail.value)}
            onInstructionDraft={(detail) => queueInstructionDraft(detail.value)}
            onInstructionCommit={(detail) => void updateInstruction(detail.value)}
            onRevealInputTemplate={() => (revealInputTemplateInUserMode = true)}
          />
        {/if}

        {#if showMcpSection}
          {#if knowledgeDisabledByMcp}
            <p
              class="label-warning border-label-default bg-label-dimmer text-label-stronger mb-2 rounded-md border px-2 py-1 text-sm"
            >
              <span class="font-bold">{m.warning()}:&nbsp;</span
              >{m.knowledge_disabled_when_mcp_active()}
            </p>
          {/if}
          <div class={knowledgeDisabledByMcp ? "pointer-events-none opacity-50" : ""}>
            <FlowStepContextSection
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
          </div>
        {/if}

        {#if showMcpSection}
          <Settings.Group title={m.mcp_servers()}>
            <Settings.Row title={m.mcp_servers()} description={m.select_mcp_servers_description()}>
              {#if mcpDisabledByKnowledge}
                <p
                  class="label-warning border-label-default bg-label-dimmer text-label-stronger mb-2 rounded-md border px-2 py-1 text-sm"
                >
                  <span class="font-bold">{m.warning()}:&nbsp;</span
                  >{m.mcp_disabled_when_knowledge_active()}
                </p>
              {/if}
              {#if !mcpCompatibilityReady}
                <p
                  class="label-warning border-label-default bg-label-dimmer text-label-stronger mb-2 rounded-md border px-2 py-1 text-sm"
                >
                  <span class="font-bold">{m.hint()}:&nbsp;</span
                  >{m.flow_step_mcp_security_context_loading()}
                </p>
              {/if}
              <div
                class={mcpDisabledByKnowledge || !mcpCompatibilityReady
                  ? "pointer-events-none opacity-50"
                  : ""}
              >
                {#if assistantState.assistant}
                  <SelectMCPServers
                    bind:selectedMCPServers={assistantState.assistant.mcp_servers}
                    bind:selectedMCPTools={assistantState.assistant.mcp_tools}
                    selectedModel={assistantState.assistant.completion_model}
                    serverCompatibilityById={flowMcpCompatibilityById}
                    on:change={(event) =>
                      assistantState.updateFields(
                        {
                          mcp_servers: event.detail.selectedMCPServers,
                          mcp_tools: event.detail.selectedMCPTools
                        },
                        { immediate: true }
                      )}
                  />
                {/if}
              </div>
            </Settings.Row>
          </Settings.Group>
        {/if}

        {#if !isTranscribeOnly && !isTemplateFill}
          <FlowStepInputTemplateSection
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
            {stepUxCopy}
            {inputTemplateSectionTitle}
            {inputTemplateSectionDescription}
            onRevealInputTemplate={() => (revealInputTemplateInUserMode = true)}
            onClearInputTemplate={() => updateInputTemplate("")}
            onInputTemplateChange={(detail) => updateInputTemplate(detail.value)}
            onInputSourceChange={(detail) =>
              handleInputSourceChange(detail.value as FlowStep["input_source"])}
          />
        {/if}

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
            step={activeStep}
            {isPublished}
            {isAdvancedMode}
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
        {/if}

        <FlowStepSecuritySection
          step={activeStep}
          {isPublished}
          onClassificationChange={(detail) =>
            updateStep("output_classification_override", detail.value)}
        />

        <!-- Typed I/O info banners -->
        {#if activeStep.output_type === "json" && activeStep.output_contract}
          <div
            class="border-accent-default/30 bg-accent-dimmer text-accent-stronger mb-3 flex items-start gap-2 rounded-lg border px-3 py-2.5 text-xs"
          >
            {m.flow_typed_io_json_contract_info()}
          </div>
        {/if}

        {#if (activeStep.output_type === "pdf" || activeStep.output_type === "docx") && activeStep.output_contract}
          <div
            class="border-accent-default/30 bg-accent-dimmer text-accent-stronger mb-3 flex items-start gap-2 rounded-lg border px-3 py-2.5 text-xs"
          >
            {m.flow_typed_io_doc_contract_info()}
          </div>
        {/if}

        {#if activeStep.input_type === "document" && activeStep.step_order === 1}
          <div
            class="border-accent-default/30 bg-accent-dimmer text-accent-stronger mb-3 flex items-start gap-2 rounded-lg border px-3 py-2.5 text-xs"
          >
            {m.flow_typed_io_document_input_info()}
          </div>
        {/if}

        {#if activeStep.input_type === "image"}
          <div
            class="border-warning-default/40 bg-warning-dimmer text-warning-stronger mb-3 flex items-start gap-2 rounded-lg border px-3 py-2.5 text-xs"
          >
            {m.flow_typed_io_image_not_supported()}
          </div>
        {/if}

        {#if isAdvancedMode && !isTemplateFill}
          <FlowStepAdvancedSection
            step={activeStep}
            {isPublished}
            {advancedJsonDrafts}
            {advancedJsonErrors}
            onJsonFieldUpdate={(detail) =>
              handleAdvancedJsonFieldUpdate(detail.field as AdvancedJsonField, detail.value)}
          />
        {/if}

        <FlowStepDeleteSection
          step={activeStep}
          {isPublished}
          onRemoveStep={() => {
            if (activeIndex >= 0) onRemoveStep?.(activeIndex);
          }}
        />
      </Settings.Page>
    </div>
  </div>
{/if}
