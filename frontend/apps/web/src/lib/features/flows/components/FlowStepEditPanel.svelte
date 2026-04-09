<svelte:options runes={false} />

<script lang="ts">
  import { IntricError, type FlowStep, type UploadedFile } from "@intric/intric-js";
  import { Settings } from "$lib/components/layout";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getIntric } from "$lib/core/Intric";
  import { initAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import { getExplicitAttachmentRules } from "$lib/features/attachments/getAttachmentRules";
  import { createEventDispatcher, onDestroy } from "svelte";
  import { get, writable } from "svelte/store";
  import { IconWorkflow } from "@intric/icons/workflow";
  import { MousePointerClick } from "lucide-svelte";
  import { Button } from "@intric/ui";
  import { Separator } from "@eneo/ui";
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
    applyTemplateInspection,
    buildTemplateBindingAutoSuggestions,
    buildTemplateBindingSuggestions,
    type FlowTemplateAssetOption,
    getTemplateFillOutputConfig,
    getTemplateFillReadiness,
    groupTemplateBindingSuggestions,
    isTemplateFillStep,
    listTemplateBindingRows,
    listTemplatePlaceholders,
    resolveTemplateAssetSelection,
    updateTemplateBinding,
    type TemplateBindingSuggestionLabels,
    type FlowTemplateInspection
  } from "$lib/features/flows/templateFillConfig";
  import { shouldShowTemplateBodyTextHint } from "$lib/features/flows/templateFillAuthoringHints";
  import { getTemplateFillErrorMessage } from "$lib/features/flows/templateFillErrors";
  import { getFlowRuntimeErrorMessage } from "$lib/features/flows/flowRuntimeErrorMapping";
  import {
    buildRuntimeInputStepPatch,
    getRuntimeInputConfig,
    type FlowRuntimeInputConfigValue
  } from "$lib/features/flows/flowRuntimeInputConfig";
  import { getFlowStepUxCopy } from "$lib/features/flows/flowStepUxCopy";
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

  // ---------------------------------------------------------------------------
  // Props
  // ---------------------------------------------------------------------------

  export let steps: FlowStep[];
  export let activeStepId: string | null;
  export let isPublished: boolean;
  export let transcriptionEnabled: boolean = true;
  export let transcriptionModelConfigured: boolean = false;
  export let transcriptionModelLabel: string | null = null;
  export let formSchema:
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

  // ---------------------------------------------------------------------------
  // Event dispatcher
  // ---------------------------------------------------------------------------

  const dispatch = createEventDispatcher<{
    stepChanged: { index: number; step: FlowStep };
    removeStep: number;
    jsonValidationChanged: { hasErrors: boolean; fields: string[] };
    openTranscriptionSettings: void;
  }>();

  // ---------------------------------------------------------------------------
  // Context & services
  // ---------------------------------------------------------------------------

  const mode = getFlowUserMode();
  const flowEditor = getFlowEditor();
  type LoadedAssistant = NonNullable<Awaited<ReturnType<typeof flowEditor.loadAssistant>>>;
  const flowResource = flowEditor.state.resource;
  $: currentFlowId = $flowResource?.id ?? "";
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
      onFileUploaded
    }
  });

  // ---------------------------------------------------------------------------
  // Core derived state
  // ---------------------------------------------------------------------------

  $: activeIndex = steps.findIndex((s) => s.id === activeStepId);
  $: activeStep = activeIndex >= 0 ? steps[activeIndex] : null;
  $: isAdvancedMode = $mode === "power_user";
  const locale = (getLocale() === "en" ? "en" : "sv") as "sv" | "en";
  $: hasAudioInputSteps = steps.some((step) => step.input_type === "audio");

  // ---------------------------------------------------------------------------
  // Input feedback state
  // ---------------------------------------------------------------------------

  let inputSourceFeedback: string | null = null;
  let inputTypeFeedback: string | null = null;
  let lastFeedbackStepKey: string | null = null;

  $: {
    const nextKey = activeStep ? `${activeStep.id ?? "new"}:${activeStep.step_order}` : null;
    if (nextKey !== lastFeedbackStepKey) {
      lastFeedbackStepKey = nextKey;
      inputSourceFeedback = null;
      inputTypeFeedback = null;
      revealInputTemplateInUserMode = false;
    }
  }

  // ---------------------------------------------------------------------------
  // Advanced JSON drafts (uses extracted reducer functions)
  // ---------------------------------------------------------------------------

  let advancedJsonDraftStepKey: string | null = null;
  let advancedJsonDrafts: AdvancedJsonDrafts = {
    input_contract: "",
    output_contract: "",
    input_config: "",
    output_config: ""
  };
  let advancedJsonErrors: AdvancedJsonErrors = {};

  function emitAdvancedJsonValidationState() {
    const fields = getErrorFields(advancedJsonErrors);
    dispatch("jsonValidationChanged", { hasErrors: fields.length > 0, fields });
  }

  $: {
    const nextStepKey = getStepKeyForAdvancedJson(activeStep);
    if (nextStepKey !== advancedJsonDraftStepKey) {
      advancedJsonDraftStepKey = nextStepKey;
      const synced = syncDraftsFromStep(activeStep);
      advancedJsonDrafts = synced.drafts;
      advancedJsonErrors = synced.errors;
      emitAdvancedJsonValidationState();
    }
  }

  $: if (activeStep !== null) {
    const updated = syncDraftsFromStepValues(advancedJsonDrafts, advancedJsonErrors, activeStep);
    if (updated) {
      advancedJsonDrafts = updated;
    }
  }

  $: if (activeStep !== null) {
    const cleaned = clearHiddenFieldErrors(advancedJsonErrors, activeStep);
    if (cleaned) {
      advancedJsonErrors = cleaned;
      emitAdvancedJsonValidationState();
    }
  }

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
  // Template fill state
  // ---------------------------------------------------------------------------

  let availableTemplateFiles: FlowTemplateAssetOption[] = [];
  let templateFilesLoaded = false;
  let templateFilesLoading = false;
  let templateInspecting = false;
  let templateInspection: FlowTemplateInspection | null = null;
  let templateConfigError: string | null = null;
  let lastTemplateInspectionKey: string | null = null;

  const templateBindingLabels: TemplateBindingSuggestionLabels = {
    formField: m.flow_template_fill_group_form(),
    aiSection: m.flow_template_fill_group_steps(),
    systemVariable: m.flow_template_fill_group_system(),
    formFieldItem: (name: string) => m.flow_template_fill_source_form({ name }),
    stepTextItem: (stepLabel: string) => m.flow_template_fill_source_step_text({ name: stepLabel }),
    stepJsonItem: (stepLabel: string) => m.flow_template_fill_source_step_json({ name: stepLabel }),
    todayDate: m.flow_template_fill_source_date(),
    leaveEmpty: m.flow_template_fill_leave_empty(),
    emptyValue: ""
  };

  // ---------------------------------------------------------------------------
  // Assistant state
  // ---------------------------------------------------------------------------

  let assistant: LoadedAssistant | null = null;
  let assistantLoading = false;
  let lastLoadedAssistantId: string | null = null;
  const autoClearedLegacyTemplateByStepId = new Set<string>();
  let stepNameBeforeEdit = "";
  let assistantLoadRequestToken = 0;
  let runningUploads: {
    id: string;
    file: File;
    status: string;
    progress: number;
    remove: () => void;
  }[] = [];

  function cancelUploadsAndClearQueue() {
    $newAttachments.forEach((upload) => {
      if (upload.status !== "completed") {
        upload.remove();
      }
    });
    clearUploads();
  }

  /* eslint-disable svelte/infinite-reactive-loop */
  $: if (activeStep?.output_mode === "template_fill") {
    assistant = null;
    lastLoadedAssistantId = null;
    assistantLoading = false;
    cancelUploadsAndClearQueue();
  } else if (activeStep?.assistant_id && activeStep.assistant_id !== lastLoadedAssistantId) {
    const targetId = activeStep.assistant_id;
    lastLoadedAssistantId = targetId;
    cancelUploadsAndClearQueue();
    void (async () => {
      await flowEditor.flushAssistantSaves().catch(() => {});
      if (activeStep?.assistant_id !== targetId) return;
      await loadAssistantForStep(targetId);
    })();
  } else if (!activeStep || !activeStep.assistant_id) {
    assistant = null;
    lastLoadedAssistantId = null;
    assistantLoading = false;
    cancelUploadsAndClearQueue();
  }
  /* eslint-enable svelte/infinite-reactive-loop */

  onDestroy(() => {
    cancelUploadsAndClearQueue();
    void flowEditor.flushAssistantSaves().catch(() => {});
  });

  $: runningUploads = $newAttachments.filter((attachment) => attachment.status !== "completed");

  $: {
    const allowed = assistant?.allowed_attachments;
    if (allowed) {
      attachmentRules.set(getExplicitAttachmentRules(allowed));
    } else {
      attachmentRules.set({});
    }
  }

  /* eslint-disable svelte/infinite-reactive-loop */
  async function loadAssistantForStep(assistantId: string) {
    if (!assistantId || assistantId === "") return;
    const requestToken = ++assistantLoadRequestToken;
    assistantLoading = true;
    lastLoadedAssistantId = assistantId;
    try {
      const loadedAssistant = await flowEditor.loadAssistant(assistantId);
      if (requestToken !== assistantLoadRequestToken) return;
      if (activeStep?.assistant_id !== assistantId) return;
      assistant = loadedAssistant;
    } catch (error) {
      if (requestToken !== assistantLoadRequestToken) return;
      console.error("Failed to load assistant for flow step:", error);
      assistant = null;
    } finally {
      if (requestToken === assistantLoadRequestToken) {
        assistantLoading = false;
      }
    }
  }
  /* eslint-enable svelte/infinite-reactive-loop */

  // ---------------------------------------------------------------------------
  // Step mutation helpers
  // ---------------------------------------------------------------------------

  function updateStep(field: string, value: unknown) {
    if (activeStep === null || activeIndex < 0) return;
    const updated = { ...activeStep, [field]: value };
    dispatch("stepChanged", { index: activeIndex, step: updated });
    if (field === "user_description" && activeStep.assistant_id) {
      flowEditor.saveAssistant(activeStep.assistant_id, { name: value });
    }
  }

  function updateStepPatch(patch: Partial<FlowStep>) {
    if (activeStep === null || activeIndex < 0) return;
    dispatch("stepChanged", { index: activeIndex, step: { ...activeStep, ...patch } });
  }

  function updateAssistantField(field: string, value: unknown) {
    if (!activeStep?.assistant_id) return;
    if (assistant) {
      assistant = { ...assistant, [field]: value };
    }
    flowEditor.saveAssistant(activeStep.assistant_id, { [field]: value });
  }

  function onFileUploaded(newFile: UploadedFile) {
    if (!assistant) return;
    const currentAttachments = Array.isArray(assistant.attachments) ? assistant.attachments : [];
    if (currentAttachments.some((file: UploadedFile) => file.id === newFile.id)) return;
    updateAssistantField("attachments", [...currentAttachments, newFile]);
  }

  async function removeAttachment(file: { id: string }) {
    if (!assistant) return;
    const uploadStillQueued = $newAttachments.find(
      (attachment) => attachment.fileRef && attachment.fileRef.id === file.id
    );
    if (uploadStillQueued) {
      try {
        await intric.files.delete({ fileId: file.id });
      } catch (error) {
        console.error("Failed to delete newly uploaded attachment file", error);
      }
    }
    const currentAttachments = Array.isArray(assistant.attachments) ? assistant.attachments : [];
    updateAssistantField(
      "attachments",
      currentAttachments.filter((attachment: UploadedFile) => attachment.id !== file.id)
    );
  }

  // ---------------------------------------------------------------------------
  // Instruction & input template
  // ---------------------------------------------------------------------------

  async function updateInstruction(value: string) {
    if (!activeStep?.assistant_id || !assistant) return;
    const nextPrompt = buildNextFlowPrompt(assistant.prompt, value);
    assistant = { ...assistant, prompt: nextPrompt };
    await flowEditor.updateAssistantImmediately(activeStep.assistant_id, { prompt: nextPrompt });
  }

  function queueInstructionDraft(value: string) {
    if (!activeStep?.assistant_id || !assistant) return;
    const nextPrompt = buildNextFlowPrompt(assistant.prompt, value);
    assistant = { ...assistant, prompt: nextPrompt };
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
    dispatch("stepChanged", { index: activeIndex, step: result.step });
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
    dispatch("stepChanged", { index: activeIndex, step: result.step });
  }

  function handleOutputModeChange(nextMode: FlowStep["output_mode"]) {
    if (activeStep === null || activeIndex < 0) return;
    dispatch("stepChanged", {
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
    dispatch("stepChanged", {
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
  // Template fill functions
  // ---------------------------------------------------------------------------

  function getFlowId() {
    return (get(flowEditor.state.resource) as { id: string }).id;
  }

  /* eslint-disable svelte/infinite-reactive-loop */
  async function loadTemplateFiles(force: boolean = false) {
    if (!force && (templateFilesLoading || templateFilesLoaded)) return;
    templateFilesLoading = true;
    try {
      const response = await intric.flows.templates.list({ id: getFlowId() });
      availableTemplateFiles = Array.isArray(response)
        ? response
        : Array.isArray((response as { items?: FlowTemplateAssetOption[] })?.items)
          ? ((response as { items: FlowTemplateAssetOption[] }).items ?? [])
          : [];
      templateFilesLoaded = true;
    } catch (error) {
      templateConfigError = getFlowRuntimeErrorMessage(
        error,
        getTemplateFillErrorMessage(error, m.flow_template_fill_template_help())
      );
    } finally {
      templateFilesLoading = false;
    }
  }

  async function inspectTemplateFile(assetId: string, options: { persist: boolean }) {
    if (!activeStep) return;
    templateInspecting = true;
    templateConfigError = null;
    try {
      const inspection = await intric.flows.templates.inspect({ id: getFlowId(), fileId: assetId });
      templateInspection = inspection;
      if (options.persist) {
        updateStep(
          "output_config",
          applyTemplateInspection(
            templateFillConfig,
            inspection,
            buildTemplateBindingAutoSuggestions({
              placeholders: inspection.placeholders.map((item: { name: string }) => item.name),
              steps,
              currentStepOrder: activeStep.step_order,
              formSchema
            })
          )
        );
      }
    } catch (error) {
      templateConfigError = getFlowRuntimeErrorMessage(
        error,
        getTemplateFillErrorMessage(error, m.flow_template_fill_template_help())
      );
    } finally {
      templateInspecting = false;
    }
  }
  /* eslint-enable svelte/infinite-reactive-loop */

  async function handleTemplateFileSelection(assetId: string) {
    if (!assetId) {
      updateStep("output_config", {
        ...templateFillConfig,
        template_asset_id: undefined,
        template_file_id: undefined,
        template_name: undefined,
        placeholders: [],
        bindings: {}
      });
      templateInspection = null;
      return;
    }
    await inspectTemplateFile(assetId, { persist: true });
  }

  async function handleTemplateUpload(event: Event) {
    const input = event.currentTarget as HTMLInputElement | null;
    const file = input?.files?.[0];
    if (!file) return;
    if (!file.name.toLowerCase().endsWith(".docx")) {
      templateConfigError = m.flow_template_fill_template_help();
      input.value = "";
      return;
    }
    templateConfigError = null;
    templateInspecting = true;
    try {
      const uploaded = await intric.flows.templates.upload({ id: getFlowId(), file });
      await loadTemplateFiles(true);
      await inspectTemplateFile(uploaded.id, { persist: true });
      toast.success(m.flow_template_fill_upload_action());
    } catch (error) {
      templateConfigError = getFlowRuntimeErrorMessage(
        error,
        getTemplateFillErrorMessage(error, m.flow_template_fill_template_help())
      );
    } finally {
      templateInspecting = false;
      if (input) input.value = "";
    }
  }

  async function downloadCurrentTemplate() {
    if (!resolvedTemplateAssetId) return;
    try {
      const { url } = await intric.flows.templates.signedUrl({
        id: getFlowId(),
        fileId: resolvedTemplateAssetId,
        contentDisposition: "attachment"
      });
      window.open(url, "_blank");
    } catch (error) {
      console.error("Failed to download template", error);
      templateConfigError = getFlowRuntimeErrorMessage(
        error,
        getTemplateFillErrorMessage(error, m.error_downloading_file())
      );
    }
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

  function updateTemplateBindingExpression(placeholder: string, expression: string) {
    updateStep("output_config", updateTemplateBinding(templateFillConfig, placeholder, expression));
  }

  function handleTemplateBindingChange(placeholder: string, value: string) {
    if (value === "__unset__") {
      const nextBindings = { ...(templateFillConfig.bindings ?? {}) };
      delete nextBindings[placeholder];
      updateStep("output_config", { ...templateFillConfig, bindings: nextBindings });
      return;
    }
    updateTemplateBindingExpression(placeholder, value);
  }

  // ---------------------------------------------------------------------------
  // Derived values for sub-components
  // ---------------------------------------------------------------------------

  $: previousStep =
    activeStep && activeStep.step_order > 1
      ? steps.find((s) => s.step_order === activeStep!.step_order - 1)
      : null;
  $: hasKnowledgeSelections = Boolean(
    assistant &&
      ((Array.isArray(assistant.websites) && assistant.websites.length > 0) ||
        (Array.isArray(assistant.groups) && assistant.groups.length > 0) ||
        (Array.isArray(assistant.integration_knowledge_list) &&
          assistant.integration_knowledge_list.length > 0))
  );
  $: hasAttachmentSelections = Boolean(
    assistant && Array.isArray(assistant.attachments) && assistant.attachments.length > 0
  );
  $: currentStepIssues = activeStep
    ? getFlowStepValidationIssues(steps).filter(
        (issue) => issue.stepOrder === activeStep.step_order
      )
    : [];
  $: sourceValidationIssue =
    currentStepIssues.find((issue) => issue.field === "input_source") ?? null;
  $: inputTypeValidationIssue =
    currentStepIssues.find((issue) => issue.field === "input_type") ?? null;
  $: sourceValidationMessage = getIssueMessage(sourceValidationIssue, activeStep, previousStep);
  $: inputTypeValidationMessage = getIssueMessage(
    inputTypeValidationIssue,
    activeStep,
    previousStep
  );

  $: selectableInputSourceOptions = activeStep
    ? getSelectableInputSourceOptions({
        steps,
        stepOrder: activeStep.step_order,
        currentInputSource: activeStep.input_source
      })
    : [];
  $: selectableInputTypeOptions = activeStep
    ? getSelectableInputTypeOptions({
        inputSource: activeStep.input_source,
        previousOutputType: previousStep?.output_type,
        currentInputType: activeStep.input_type,
        isAdvancedMode
      })
    : [];
  $: displayedInputTypeOptions = activeStep
    ? sortSelectableInputTypeOptionsForDisplay({
        options: selectableInputTypeOptions,
        inputSource: activeStep.input_source,
        previousOutputType: previousStep?.output_type
      })
    : [];
  $: sourceHintKind = activeStep
    ? getSourceHintKind({
        inputSource: activeStep.input_source,
        previousOutputType: previousStep?.output_type
      })
    : null;
  $: outputHintKind = activeStep ? getOutputHintKind(activeStep.output_type) : null;

  $: stepSummaryModel = activeStep
    ? getStepSummaryModel({
        step: activeStep,
        previousStep,
        hasInputTemplateOverride,
        hasKnowledge: hasKnowledgeSelections,
        hasAttachments: hasAttachmentSelections
      })
    : null;

  $: isTemplateFill = isTemplateFillStep(activeStep);
  $: templateFillConfig = getTemplateFillOutputConfig(activeStep);
  $: templatePlaceholders = listTemplatePlaceholders(templateInspection, templateFillConfig);
  $: templateBindingSuggestions = activeStep
    ? buildTemplateBindingSuggestions({
        steps,
        currentStepOrder: activeStep.step_order,
        labels: templateBindingLabels,
        formSchema
      })
    : [];
  $: templateBindingSuggestionGroups = groupTemplateBindingSuggestions(
    templateBindingSuggestions,
    templateBindingLabels
  );
  $: templateAutoBindings = activeStep
    ? buildTemplateBindingAutoSuggestions({
        placeholders: templatePlaceholders.map((item) => item.name),
        steps,
        currentStepOrder: activeStep.step_order,
        formSchema
      })
    : {};
  $: templateBindingRows = listTemplateBindingRows({
    inspection: templateInspection,
    currentConfig: templateFillConfig,
    suggestions: templateBindingSuggestions,
    autoSuggestions: templateAutoBindings,
    labels: templateBindingLabels
  });
  $: templateReadiness = getTemplateFillReadiness(templateFillConfig);
  $: runtimeInputConfig = activeStep
    ? getRuntimeInputConfig(activeStep)
    : ({
        enabled: false,
        required: false,
        max_files: null,
        input_format: "document",
        accepted_mimetypes_override: [],
        label: "",
        description: ""
      } satisfies FlowRuntimeInputConfigValue);

  $: templateOrphanedRows = templateBindingRows.filter((row) => row.status === "orphaned");
  $: templateHasSelection = Boolean(
    templateFillConfig.template_asset_id ?? templateFillConfig.template_file_id
  );
  $: resolvedTemplateAssetSelection = resolveTemplateAssetSelection(
    templateFillConfig,
    availableTemplateFiles
  );
  $: resolvedTemplateAssetId = resolvedTemplateAssetSelection.assetId;
  $: selectedTemplateAsset = resolvedTemplateAssetSelection.asset;
  $: templateUnnamedStepWarning =
    isTemplateFill &&
    steps.some(
      (step) =>
        step.step_order < (activeStep?.step_order ?? Number.MAX_SAFE_INTEGER) &&
        (!step.user_description || !step.user_description.trim())
    );
  $: templateAutoMatchableCount = templateBindingRows.filter(
    (row) => row.status === "missing" && Boolean(templateAutoBindings[row.placeholderName])
  ).length;

  // Output type/mode options
  $: availableOutputTypes =
    activeStep?.output_mode === "transcribe_only"
      ? OUTPUT_TYPES.filter((type) => type.value === "text")
      : activeStep?.output_mode === "template_fill"
        ? OUTPUT_TYPES.filter((type) => type.value === "docx")
        : OUTPUT_TYPES;
  $: availableOutputModes = (() => {
    const base =
      activeStep?.input_type === "audio"
        ? OUTPUT_MODES
        : OUTPUT_MODES.filter((mode) => mode.value !== "transcribe_only");
    const visible =
      isAdvancedMode || activeStep?.output_mode === "template_fill"
        ? base
        : base.filter((mode) => mode.value !== "template_fill");
    return visible;
  })();
  $: isTranscribeOnly = activeStep?.output_mode === "transcribe_only";

  // Instruction & input template derived
  $: instructionText =
    assistant &&
    typeof assistant === "object" &&
    assistant.prompt &&
    typeof assistant.prompt === "object"
      ? (assistant.prompt.text ?? "")
      : "";
  $: inputTemplateText =
    activeStep && activeStep.input_bindings && typeof activeStep.input_bindings === "object"
      ? ((activeStep.input_bindings.question as string) ?? "")
      : "";
  $: hasInputTemplateOverride = inputTemplateText.trim().length > 0;
  let revealInputTemplateInUserMode = false;
  $: canRevealInputTemplate = !isTranscribeOnly && activeStep !== null && !isAdvancedMode;
  $: showInputTemplate =
    isAdvancedMode || (canRevealInputTemplate && revealInputTemplateInUserMode);
  $: stepUxCopy = getFlowStepUxCopy({ locale, inputSource: activeStep?.input_source });
  $: inputTemplateSectionTitle = stepUxCopy.inputTemplateTitle;
  $: inputTemplateSectionDescription = stepUxCopy.inputTemplateDescription;

  $: templateStepRefs = (() => {
    if (!inputTemplateText) return [];
    const refs: number[] = [];
    const regex = /\{\{\s*step_(\d+)\./g;
    let match;
    while ((match = regex.exec(inputTemplateText)) !== null) {
      refs.push(parseInt(match[1], 10));
    }
    return [...new Set(refs)];
  })();

  $: templateSourceConflict = (() => {
    if (!activeStep || templateStepRefs.length === 0) return null;
    if (activeStep.input_source === "all_previous_steps") return null;
    if (activeStep.input_source === "previous_step") {
      const connected = activeStep.step_order - 1;
      const unconnected = templateStepRefs.filter((r) => r !== connected);
      return unconnected.length > 0 ? unconnected : null;
    }
    return templateStepRefs;
  })();

  // ---------------------------------------------------------------------------
  // Template inspection reactive triggers
  // ---------------------------------------------------------------------------

  $: {
    const nextTemplateKey =
      activeStep && isTemplateFill
        ? `${activeStep.id ?? "new"}:${resolvedTemplateAssetId ?? ""}`
        : null;
    if (nextTemplateKey !== lastTemplateInspectionKey) {
      lastTemplateInspectionKey = nextTemplateKey;
      templateInspection = null;
      templateConfigError = null;
      if (nextTemplateKey && resolvedTemplateAssetId) {
        // eslint-disable-next-line svelte/infinite-reactive-loop
        void inspectTemplateFile(resolvedTemplateAssetId, { persist: false });
      }
    }
  }

  $: if (isAdvancedMode && isTemplateFill && !templateFilesLoaded && !templateFilesLoading) {
    // eslint-disable-next-line svelte/infinite-reactive-loop
    void loadTemplateFiles();
  }

  // ---------------------------------------------------------------------------
  // Guard reactive blocks
  // ---------------------------------------------------------------------------

  // Legacy cleanup: old builder versions could accidentally mirror instruction -> input template.
  $: if (
    activeStep?.id &&
    !isPublished &&
    hasInputTemplateOverride &&
    instructionText.trim().length > 0 &&
    inputTemplateText.trim() === instructionText.trim() &&
    !autoClearedLegacyTemplateByStepId.has(activeStep.id)
  ) {
    autoClearedLegacyTemplateByStepId.add(activeStep.id);
    updateInputTemplate("");
  }

  $: if (
    activeStep &&
    activeIndex >= 0 &&
    activeStep.output_mode === "transcribe_only" &&
    activeStep.output_type !== "text"
  ) {
    updateStep("output_type", "text");
  }

  $: if (
    activeStep &&
    activeIndex >= 0 &&
    activeStep.input_type !== "audio" &&
    activeStep.output_mode === "transcribe_only"
  ) {
    updateStep("output_mode", "pass_through");
  }
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
        <Button variant="primary" on:click={() => flowEditor.addStep()}>
          {m.flow_empty_add_step()}
        </Button>
      {/if}
    </div>
  {:else}
    <div class="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
      <MousePointerClick class="size-10 text-muted/40 mb-3" />
      <h3 class="text-lg font-semibold">{m.flow_step_select_prompt()}</h3>
      <p class="text-secondary max-w-md text-sm">
        {m.flow_step_select_prompt_desc()}
      </p>
    </div>
  {/if}
{:else}
  <div
    class="p-4 pb-8 lg:p-6 lg:pb-8"
    class:pointer-events-none={isPublished}
    class:opacity-60={isPublished}
  >
    <div
      class="flow-step-editor [&_section>div:last-child]:gap-6 [&_section>div:last-child]:pb-6 [&_section>h2]:font-sans [&_section>h2]:tracking-[0.04em] [&_section>h2]:uppercase"
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
                on:focus={() => {
                  stepNameBeforeEdit = activeStep.user_description ?? "";
                }}
                on:input={(e) => updateStep("user_description", e.currentTarget.value || null)}
                on:change={() => void handleCommittedStepRename()}
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
            on:inputSourceChange={(e) => handleInputSourceChange(e.detail.value)}
            on:inputTypeChange={(e) => handleInputTypeChange(e.detail.value)}
            on:runtimeInputChange={(e) => updateRuntimeInputSettings(e.detail.patch)}
            on:httpConfigChange={(e) => updateStep("input_config", e.detail.config)}
            on:openTranscriptionSettings={() => dispatch("openTranscriptionSettings")}
          />
        {/if}

        {#if !isTemplateFill}
          <FlowStepBehaviorSection
            step={activeStep}
            {isPublished}
            {isAdvancedMode}
            {isTranscribeOnly}
            {assistant}
            {assistantLoading}
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
            on:assistantFieldChange={(e) => updateAssistantField(e.detail.field, e.detail.value)}
            on:instructionDraft={(e) => queueInstructionDraft(e.detail.value)}
            on:instructionCommit={(e) => void updateInstruction(e.detail.value)}
            on:revealInputTemplate={() => (revealInputTemplateInUserMode = true)}
          />
        {/if}

        {#if !isTranscribeOnly && !isTemplateFill}
          <FlowStepContextSection
            {assistant}
            {assistantLoading}
            {runningUploads}
            on:knowledgeChange={(e) => {
              updateAssistantField("websites", e.detail.websites);
              updateAssistantField("groups", e.detail.groups);
              updateAssistantField("integration_knowledge_list", e.detail.integrationKnowledgeList);
            }}
            on:removeAttachment={(e) => void removeAttachment(e.detail.file)}
          />
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
            on:revealInputTemplate={() => (revealInputTemplateInUserMode = true)}
            on:clearInputTemplate={() => updateInputTemplate("")}
            on:inputTemplateChange={(e) => updateInputTemplate(e.detail.value)}
            on:inputSourceChange={(e) => handleInputSourceChange(e.detail.value)}
          />
        {/if}

        {#if isTemplateFill}
          <FlowStepTemplateFillSection
            step={activeStep}
            {isPublished}
            {isAdvancedMode}
            {templateFillConfig}
            {templateInspection}
            {templateInspecting}
            {templateConfigError}
            {templateFilesLoading}
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
            {availableTemplateFiles}
            on:outputModeChange={(e) => handleOutputModeChange(e.detail.value)}
            on:templateFileSelect={(e) => void handleTemplateFileSelection(e.detail.assetId)}
            on:templateUpload={(e) => void handleTemplateUpload(e.detail.event)}
            on:templateDownload={() => void downloadCurrentTemplate()}
            on:templateRefresh={() =>
              resolvedTemplateAssetId &&
              void inspectTemplateFile(resolvedTemplateAssetId, { persist: false })}
            on:bindingChange={(e) =>
              handleTemplateBindingChange(e.detail.placeholder, e.detail.value)}
            on:applyAllSuggestions={applyAllTemplateSuggestions}
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
            on:outputTypeChange={(e) => handleOutputTypeChange(e.detail.value)}
            on:outputModeChange={(e) => handleOutputModeChange(e.detail.value)}
            on:webhookUrlChange={(e) =>
              updateStep("output_config", {
                ...(activeStep?.output_config ?? {}),
                url: e.detail.value
              })}
            on:httpConfigChange={(e) =>
              updateStep(
                "output_config",
                preserveFlowCitationMode(e.detail.config, activeStep?.output_config ?? null)
              )}
            on:citationModeChange={(e) => handleCitationModeChange(e.detail.value)}
            on:switchToTemplateFill={() => handleOutputModeChange("template_fill")}
          />
        {/if}

        <FlowStepSecuritySection
          step={activeStep}
          {isPublished}
          on:classificationChange={(e) =>
            updateStep("output_classification_override", e.detail.value)}
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
            on:mcpPolicyChange={(e) => updateStep("mcp_policy", e.detail.value)}
            on:jsonFieldUpdate={(e) =>
              handleAdvancedJsonFieldUpdate(e.detail.field, e.detail.value)}
          />
        {/if}

        <FlowStepDeleteSection
          step={activeStep}
          {isPublished}
          on:removeStep={() => {
            if (activeIndex >= 0) dispatch("removeStep", activeIndex);
          }}
        />
      </Settings.Page>
    </div>
  </div>
{/if}
