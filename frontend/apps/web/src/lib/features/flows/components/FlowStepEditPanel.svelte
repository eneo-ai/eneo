<script lang="ts">
  import { IntricError, type FlowStep, type UploadedFile } from "@intric/intric-js";
  import { Settings } from "$lib/components/layout";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import FlowPromptEditor from "./FlowPromptEditor.svelte";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectBehaviourV2 from "$lib/features/ai-models/components/SelectBehaviourV2.svelte";
  import SelectKnowledgeV2 from "$lib/features/knowledge/components/SelectKnowledgeV2.svelte";
  import { getIntric } from "$lib/core/Intric";
  import { initAttachmentManager } from "$lib/features/attachments/AttachmentManager";
  import { getExplicitAttachmentRules } from "$lib/features/attachments/getAttachmentRules";
  import AttachmentUploadTextButton from "$lib/features/attachments/components/AttachmentUploadTextButton.svelte";
  import UploadedFileIcon from "$lib/features/attachments/components/UploadedFileIcon.svelte";
  import AttachmentPreview from "$lib/features/attachments/components/AttachmentPreview.svelte";
  import { formatBytes } from "$lib/core/formatting/formatBytes";
  import { formatFileType } from "$lib/core/formatting/formatFileType";
  import { supportsTemperature } from "$lib/features/ai-models/supportsTemperature.js";
  import PromptVersionDialog from "$lib/features/prompts/components/PromptVersionDialog.svelte";
  import { createEventDispatcher, onDestroy } from "svelte";
  import { writable } from "svelte/store";
  import { IconCancel } from "@intric/icons/cancel";
  import { IconTrash } from "@intric/icons/trash";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconWorkflow } from "@intric/icons/workflow";
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { IconMicrophone } from "@intric/icons/microphone";
  import { IconLockClosed } from "@intric/icons/lock-closed";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { Button, Dialog, Tooltip } from "@intric/ui";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { slide } from "svelte/transition";
  import {
    getFlowStepValidationIssues,
    getPreferredInputType,
    getSelectableInputSourceOptions,
    getSelectableInputTypeOptions,
    type FlowStepValidationIssue,
  } from "$lib/features/flows/flowStepTypes";

  export let steps: FlowStep[];
  export let activeStepId: string | null;
  export let isPublished: boolean;
  export let transcriptionEnabled: boolean = true;
  export let transcriptionModelConfigured: boolean = false;
  export let transcriptionModelLabel: string | null = null;
  export let formSchema: { fields: { name: string; type: string; required?: boolean; options?: string[]; order?: number }[] } | undefined;

  const dispatch = createEventDispatcher<{
    stepChanged: { index: number; step: FlowStep };
    removeStep: number;
    jsonValidationChanged: { hasErrors: boolean; fields: string[] };
    openTranscriptionSettings: void;
  }>();

  const mode = getFlowUserMode();
  const flowEditor = getFlowEditor();
  type LoadedAssistant = NonNullable<Awaited<ReturnType<typeof flowEditor.loadAssistant>>>;
  const { state: { currentSpace } } = getSpacesManager();
  const intric = getIntric();
  const attachmentRules = writable({});
  const {
    state: { attachments: newAttachments },
    clearUploads
  } = initAttachmentManager({
    intric,
    options: {
      rules: attachmentRules,
      onFileUploaded,
    },
  });

  $: activeIndex = steps.findIndex((s) => s.id === activeStepId);
  $: activeStep = activeIndex >= 0 ? steps[activeIndex] : null;
  $: isAdvancedMode = $mode === "power_user";
  $: hasAudioInputSteps = steps.some((step) => step.input_type === "audio");
  let inputSourceFeedback: string | null = null;
  let inputTypeFeedback: string | null = null;
  let lastFeedbackStepKey: string | null = null;

  type AdvancedJsonField = "input_contract" | "output_contract" | "input_config" | "output_config";
  const ADVANCED_JSON_FIELDS: AdvancedJsonField[] = [
    "input_contract",
    "output_contract",
    "input_config",
    "output_config",
  ];
  let advancedJsonDraftStepKey: string | null = null;
  let advancedJsonDrafts: Record<AdvancedJsonField, string> = {
    input_contract: "",
    output_contract: "",
    input_config: "",
    output_config: "",
  };
  let advancedJsonErrors: Partial<Record<AdvancedJsonField, string>> = {};

  function getStepKeyForAdvancedJson(step: FlowStep | null): string | null {
    if (!step) return null;
    return `${step.id ?? "new"}:${step.step_order}`;
  }

  function formatAdvancedJson(value: unknown): string {
    return value == null ? "" : JSON.stringify(value, null, 2);
  }

  function getStepAdvancedJsonValue(step: FlowStep, field: AdvancedJsonField): unknown {
    switch (field) {
      case "input_contract":
        return step.input_contract;
      case "output_contract":
        return step.output_contract;
      case "input_config":
        return step.input_config;
      case "output_config":
        return step.output_config;
      default:
        return null;
    }
  }

  function getVisibleAdvancedJsonFields(step: FlowStep | null): Set<AdvancedJsonField> {
    const visible = new Set<AdvancedJsonField>(["input_contract", "output_contract"]);
    if (step && (step.input_source === "http_get" || step.input_source === "http_post")) {
      visible.add("input_config");
    }
    if (step?.output_mode === "http_post") {
      visible.add("output_config");
    }
    return visible;
  }

  function emitAdvancedJsonValidationState() {
    const fields = ADVANCED_JSON_FIELDS.filter((field) => Boolean(advancedJsonErrors[field]));
    dispatch("jsonValidationChanged", { hasErrors: fields.length > 0, fields });
  }

  function syncAdvancedJsonDrafts(step: FlowStep | null) {
    advancedJsonDrafts = {
      input_contract: formatAdvancedJson(step?.input_contract ?? null),
      output_contract: formatAdvancedJson(step?.output_contract ?? null),
      input_config: formatAdvancedJson(step?.input_config ?? null),
      output_config: formatAdvancedJson(step?.output_config ?? null),
    };
    advancedJsonErrors = {};
    emitAdvancedJsonValidationState();
  }

  function clearAdvancedJsonError(field: AdvancedJsonField) {
    if (!advancedJsonErrors[field]) return;
    const nextErrors = { ...advancedJsonErrors };
    delete nextErrors[field];
    advancedJsonErrors = nextErrors;
    emitAdvancedJsonValidationState();
  }

  function setAdvancedJsonError(field: AdvancedJsonField, message: string) {
    const currentMessage = advancedJsonErrors[field];
    if (currentMessage === message) return;
    advancedJsonErrors = { ...advancedJsonErrors, [field]: message };
    emitAdvancedJsonValidationState();
  }

  function updateAdvancedJsonField(field: AdvancedJsonField, rawValue: string) {
    advancedJsonDrafts = { ...advancedJsonDrafts, [field]: rawValue };
    const trimmed = rawValue.trim();
    if (trimmed.length === 0) {
      clearAdvancedJsonError(field);
      updateStep(field, null);
      return;
    }
    try {
      const parsed = JSON.parse(rawValue);
      clearAdvancedJsonError(field);
      updateStep(field, parsed);
    } catch (error) {
      const detail =
        error instanceof Error && error.message.trim().length > 0
          ? error.message
          : "Invalid JSON syntax";
      setAdvancedJsonError(field, `${m.flow_run_error()}: ${detail}`);
    }
  }

  // Assistant state for the active step
  let assistant: LoadedAssistant | null = null;
  let assistantLoading = false;
  let lastLoadedAssistantId: string | null = null;
  const autoClearedLegacyTemplateByStepId = new Set<string>();
  let stepNameBeforeEdit = "";
  let assistantLoadRequestToken = 0;
  let runningUploads: { id: string; file: File; status: string; progress: number; remove: () => void }[] = [];

  function cancelUploadsAndClearQueue() {
    $newAttachments.forEach((upload) => {
      if (upload.status !== "completed") {
        upload.remove();
      }
    });
    clearUploads();
  }

  // Load assistant when active step changes.
  $: if (activeStep?.assistant_id && activeStep.assistant_id !== lastLoadedAssistantId) {
    void flowEditor.flushAssistantSaves().catch(() => {
      // Save errors are surfaced in editor validation/toasts.
    });
    cancelUploadsAndClearQueue();
    // eslint-disable-next-line svelte/infinite-reactive-loop
    void loadAssistantForStep(activeStep.assistant_id);
  } else if (!activeStep || !activeStep.assistant_id) {
    assistant = null;
    lastLoadedAssistantId = null;
    assistantLoading = false;
    cancelUploadsAndClearQueue();
  }

  onDestroy(() => {
    cancelUploadsAndClearQueue();
    void flowEditor.flushAssistantSaves().catch(() => {
      // Best-effort flush on unmount.
    });
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

  /* eslint-disable svelte/infinite-reactive-loop --
    Guarded async assistant sync intentionally mutates local component state in
    response to active-step changes. Request tokens and assistant-id checks
    prevent stale results from causing feedback loops.
  */
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

  function updateInstruction(value: string) {
    if (!activeStep?.assistant_id || !assistant?.prompt) return;
    const nextPrompt = { ...assistant.prompt, text: value, description: "" };
    assistant = { ...assistant, prompt: nextPrompt };
    flowEditor.saveAssistant(activeStep.assistant_id, { prompt: nextPrompt });
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
        newName,
      });
    } catch (error) {
      const message =
        error instanceof IntricError
          ? error.getReadableMessage()
          : "Failed to rewrite downstream variable references.";
      toast.error(message);
    }
  }

  function sanitizeBindingsForSource(
    bindings: Record<string, unknown> | null | undefined
  ): Record<string, unknown> | null {
    const nextBindings: Record<string, unknown> = { ...(bindings ?? {}) };
    delete nextBindings.text;
    return Object.keys(nextBindings).length > 0 ? nextBindings : null;
  }

  function handleInputSourceChange(nextSource: FlowStep["input_source"]) {
    if (activeStep === null || activeIndex < 0) return;
    inputSourceFeedback = null;
    inputTypeFeedback = null;
    const httpSourceSelected = nextSource === "http_get" || nextSource === "http_post";
    const nextPreviousOutputType = nextSource === "previous_step" ? previousStep?.output_type : undefined;
    const nextInputTypeOptions = getSelectableInputTypeOptions({
      inputSource: nextSource,
      previousOutputType: nextPreviousOutputType,
      currentInputType: activeStep.input_type,
      isAdvancedMode,
    });
    const nextInputConfig = (() => {
      if (!httpSourceSelected) return activeStep.input_config ?? null;
      const currentConfig =
        activeStep.input_config && typeof activeStep.input_config === "object"
          ? (activeStep.input_config as Record<string, unknown>)
          : {};
      return {
        ...currentConfig,
        timeout_seconds:
          typeof currentConfig.timeout_seconds === "number"
            ? currentConfig.timeout_seconds
            : 30,
        url:
          typeof currentConfig.url === "string"
            ? currentConfig.url
            : "",
      };
    })();
    const nextInputType = nextInputTypeOptions.some(
      (option) => option.value === activeStep.input_type && !option.disabled && !option.legacyInvalid
    )
      ? activeStep.input_type
      : getPreferredInputType({
          inputSource: nextSource,
          previousOutputType: nextPreviousOutputType,
          isAdvancedMode,
        });
    if (nextInputType !== activeStep.input_type) {
      inputTypeFeedback = m.flow_step_input_type_adjusted({
        inputType: getInputTypeLabel(nextInputType),
      });
    }
    const updated = {
      ...activeStep,
      input_source: nextSource,
      input_type: nextInputType,
      input_config: nextInputConfig,
      input_bindings: sanitizeBindingsForSource(
        activeStep.input_bindings as Record<string, unknown> | null | undefined
      )
    };
    dispatch("stepChanged", { index: activeIndex, step: updated });
  }

  function handleInputTypeChange(nextType: FlowStep["input_type"]) {
    if (activeStep === null || activeIndex < 0) return;
    inputSourceFeedback = null;
    inputTypeFeedback = null;
    const isAudioInput = nextType === "audio";
    const nextOutputMode: FlowStep["output_mode"] =
      isAudioInput
        ? "transcribe_only"
        : activeStep.output_mode === "transcribe_only"
          ? "pass_through"
          : activeStep.output_mode;
    const nextOutputType: FlowStep["output_type"] = isAudioInput ? "text" : activeStep.output_type;
    const nextInputSource: FlowStep["input_source"] =
      (nextType === "document" || nextType === "audio" || nextType === "file") &&
      activeStep.input_source !== "flow_input"
        ? "flow_input"
        : activeStep.input_source;
    if (nextInputSource !== activeStep.input_source) {
      inputSourceFeedback = m.flow_step_input_source_adjusted({
        inputSource: getInputSourceLabel(nextInputSource),
      });
    }
    const updated: FlowStep = {
      ...activeStep,
      input_type: nextType,
      input_source: nextInputSource,
      output_mode: nextOutputMode,
      output_type: nextOutputType,
    };
    dispatch("stepChanged", { index: activeIndex, step: updated });
  }

  function handleOutputModeChange(nextMode: FlowStep["output_mode"]) {
    if (activeStep === null || activeIndex < 0) return;
    if (nextMode === "transcribe_only") {
      dispatch("stepChanged", {
        index: activeIndex,
        step: {
          ...activeStep,
          input_type: "audio",
          input_source: "flow_input",
          output_mode: "transcribe_only",
          output_type: "text",
        },
      });
      return;
    }
    dispatch("stepChanged", {
      index: activeIndex,
      step: { ...activeStep, output_mode: nextMode },
    });
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

  $: instructionText =
    assistant && typeof assistant === "object" && assistant.prompt && typeof assistant.prompt === "object"
      ? (assistant.prompt.text ?? "")
      : "";
  $: inputTemplateText =
    activeStep && activeStep.input_bindings && typeof activeStep.input_bindings === "object"
      ? ((activeStep.input_bindings.question as string) ?? "")
      : "";
  $: showInputTemplate = $mode === "power_user" ||
    (activeStep !== null && activeStep.input_source !== "flow_input" && hasInputTemplateOverride);
  $: hasInputTemplateOverride = inputTemplateText.trim().length > 0;

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
      const unconnected = templateStepRefs.filter(r => r !== connected);
      return unconnected.length > 0 ? unconnected : null;
    }
    return templateStepRefs;
  })();

  $: {
    const nextStepKey = getStepKeyForAdvancedJson(activeStep);
    if (nextStepKey !== advancedJsonDraftStepKey) {
      advancedJsonDraftStepKey = nextStepKey;
      syncAdvancedJsonDrafts(activeStep);
    }
  }

  $: if (activeStep !== null) {
    const nextDrafts = { ...advancedJsonDrafts };
    let changed = false;
    for (const field of ADVANCED_JSON_FIELDS) {
      if (advancedJsonErrors[field]) continue;
      const nextValue = formatAdvancedJson(getStepAdvancedJsonValue(activeStep, field));
      if (nextDrafts[field] !== nextValue) {
        nextDrafts[field] = nextValue;
        changed = true;
      }
    }
    if (changed) {
      advancedJsonDrafts = nextDrafts;
    }
  }

  $: if (activeStep !== null) {
    const visibleFields = getVisibleAdvancedJsonFields(activeStep);
    const nextErrors = { ...advancedJsonErrors };
    let changed = false;
    for (const field of ADVANCED_JSON_FIELDS) {
      if (!visibleFields.has(field) && nextErrors[field]) {
        delete nextErrors[field];
        changed = true;
      }
    }
    if (changed) {
      advancedJsonErrors = nextErrors;
      emitAdvancedJsonValidationState();
    }
  }

  const INPUT_SOURCE_LABELS: Record<string, () => string> = {
    flow_input: () => m.flow_input_source_flow_input(),
    previous_step: () => m.flow_input_source_previous_step(),
    all_previous_steps: () => m.flow_input_source_all_previous_steps(),
    http_get: () => m.flow_input_source_http_get(),
    http_post: () => m.flow_input_source_http_post(),
  };

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

  function updateStep(field: string, value: unknown) {
    if (activeStep === null || activeIndex < 0) return;
    const updated = { ...activeStep, [field]: value };
    dispatch("stepChanged", { index: activeIndex, step: updated });

    // Sync step name to hidden assistant
    if (field === "user_description" && activeStep.assistant_id) {
      flowEditor.saveAssistant(activeStep.assistant_id, { name: value });
    }
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
      currentAttachments.filter((attachment: UploadedFile) => attachment.id !== file.id),
    );
  }

  $: previousStep = activeStep && activeStep.step_order > 1
    ? steps.find((s) => s.step_order === activeStep!.step_order - 1)
    : null;
  $: currentStepIssues = activeStep
    ? getFlowStepValidationIssues(steps).filter((issue) => issue.stepOrder === activeStep.step_order)
    : [];
  $: sourceValidationIssue = currentStepIssues.find((issue) => issue.field === "input_source") ?? null;
  $: inputTypeValidationIssue = currentStepIssues.find((issue) => issue.field === "input_type") ?? null;
  $: selectableInputSourceOptions = activeStep
    ? getSelectableInputSourceOptions({
        steps,
        stepOrder: activeStep.step_order,
        currentInputSource: activeStep.input_source,
      })
    : [];
  $: selectableInputTypeOptions = activeStep
    ? getSelectableInputTypeOptions({
        inputSource: activeStep.input_source,
        previousOutputType: previousStep?.output_type,
        currentInputType: activeStep.input_type,
        isAdvancedMode,
      })
    : [];

  const INPUT_TYPES = [
    { value: "text", get label() { return m.flow_type_text(); } },
    { value: "json", get label() { return m.flow_type_json(); } },
    { value: "document", get label() { return m.flow_type_document(); } },
    { value: "file", get label() { return m.flow_type_file(); } },
    { value: "image", get label() { return m.flow_type_image(); } },
    { value: "audio", get label() { return m.flow_type_audio(); } },
    { value: "any", get label() { return m.flow_type_any(); } },
  ];
  const OUTPUT_TYPES = [
    { value: "text", get label() { return m.flow_output_type_text(); } },
    { value: "json", get label() { return m.flow_output_type_json(); } },
    { value: "pdf", get label() { return m.flow_output_type_pdf(); } },
    { value: "docx", get label() { return m.flow_output_type_docx(); } },
  ];
  $: availableOutputTypes =
    activeStep?.output_mode === "transcribe_only"
      ? OUTPUT_TYPES.filter((type) => type.value === "text")
      : OUTPUT_TYPES;

  const INPUT_SOURCE_HINTS: Record<string, () => string> = {
    flow_input: () => m.flow_input_source_hint_flow_input(),
    previous_step: () => m.flow_input_source_hint_previous_step(),
    all_previous_steps: () => m.flow_input_source_hint_all_previous_steps(),
  };
  const OUTPUT_MODES = [
    { value: "pass_through", get label() { return m.flow_output_mode_pass_through(); } },
    { value: "transcribe_only", get label() { return m.flow_output_mode_transcribe_only(); } },
    { value: "http_post", get label() { return m.flow_output_mode_http_post(); } }
  ];
  $: availableOutputModes =
    activeStep?.input_type === "audio"
      ? OUTPUT_MODES
      : OUTPUT_MODES.filter((mode) => mode.value !== "transcribe_only");
  const MCP_POLICIES = [
    { value: "inherit", get label() { return m.flow_mcp_policy_inherit(); } },
    { value: "restricted", get label() { return m.flow_mcp_policy_restricted(); } }
  ];
  $: isTranscribeOnly = activeStep?.output_mode === "transcribe_only";

  $: {
    const nextKey = activeStep ? `${activeStep.id ?? "new"}:${activeStep.step_order}` : null;
    if (nextKey !== lastFeedbackStepKey) {
      lastFeedbackStepKey = nextKey;
      inputSourceFeedback = null;
      inputTypeFeedback = null;
    }
  }

  function getInputTypeLabel(value: string) {
    return INPUT_TYPES.find((type) => type.value === value)?.label ?? value;
  }

  function getInputSourceLabel(value: string) {
    return INPUT_SOURCE_LABELS[value]?.() ?? value;
  }

  function getInputSourceOptionLabel(value: string, legacyInvalid: boolean) {
    const label = getInputSourceLabel(value);
    return legacyInvalid ? `${label} (${m.flow_step_legacy_invalid_option()})` : label;
  }

  function getInputTypeOptionLabel(value: string, legacyInvalid: boolean) {
    const label = getInputTypeLabel(value);
    return legacyInvalid ? `${label} (${m.flow_step_legacy_invalid_option()})` : label;
  }

  function getIssueMessage(issue: FlowStepValidationIssue | null): string | null {
    if (!issue || !activeStep) return null;
    switch (issue.code) {
      case "typed_io_multiple_flow_input_steps":
      case "typed_io_flow_input_position_invalid":
        return m.flow_step_issue_flow_input_position();
      case "typed_io_invalid_input_source_position":
        return m.flow_step_issue_first_step_input_source();
      case "typed_io_missing_previous_step":
        return m.flow_step_issue_missing_previous_step();
      case "typed_io_document_source_unsupported":
      case "typed_io_audio_source_unsupported":
      case "typed_io_file_source_unsupported":
        return m.flow_step_issue_flow_input_only({
          inputType: getInputTypeLabel(activeStep.input_type),
        });
      case "typed_io_invalid_input_source_combination":
        return m.flow_step_issue_all_previous_steps_json();
      case "typed_io_incompatible_type_chain":
        return previousStep
          ? m.flow_typed_io_chain_incompatible({
              outputType: previousStep.output_type,
              inputType: activeStep.input_type,
              prevStep: String(previousStep.step_order),
            })
          : m.flow_step_issue_missing_previous_step();
      case "typed_io_unsupported_type":
        return activeStep.input_type === "image"
          ? m.flow_typed_io_image_not_supported()
          : null;
      default:
        return null;
    }
  }

  $: sourceValidationMessage = getIssueMessage(sourceValidationIssue);
  $: inputTypeValidationMessage = getIssueMessage(inputTypeValidationIssue);

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

  let showDeleteConfirm: Dialog.OpenState;
</script>

{#if activeStep === null}
  {#if steps.length === 0}
    <!-- Welcome empty state -->
    <div class="flex h-full flex-col items-center justify-center gap-5 px-8 text-center">
      <div class="bg-hover-dimmer flex size-16 items-center justify-center rounded-2xl shadow-sm">
        <IconWorkflow class="size-8 text-secondary" />
      </div>
      <div class="flex flex-col gap-2">
        <h3 class="text-lg font-semibold">{m.flow_no_steps_welcome_title()}</h3>
        <p class="text-secondary max-w-md text-sm leading-relaxed">{m.flow_no_steps_welcome_description()}</p>
      </div>
      {#if !isPublished}
        <Button variant="primary" on:click={() => flowEditor.addStep()}>
          {m.flow_empty_add_step()}
        </Button>
      {/if}
    </div>
  {:else}
    <div class="flex h-full flex-col items-center justify-center gap-3 px-8 text-center">
      <h3 class="text-lg font-semibold">{m.flow_step_select_prompt()}</h3>
      <p class="max-w-md text-sm text-secondary">
        {m.flow_step_select_prompt_desc()}
      </p>
    </div>
  {/if}
{:else}
  <div class="p-4 pb-8 lg:p-6 lg:pb-8" class:pointer-events-none={isPublished} class:opacity-60={isPublished}>
    <div class="flow-step-editor [&_section>div:last-child]:gap-6 [&_section>div:last-child]:pb-6">
    <Settings.Page>
      <!-- Data Source Section -->
      <Settings.Group title={m.flow_step_input_source()}>
        <Settings.Row title={m.flow_step_name()} description="" let:aria>
          <input
            {...aria}
            type="text"
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            value={activeStep.user_description ?? ""}
            placeholder={m.flow_step_name_placeholder()}
            disabled={isPublished}
            on:focus={() => {
              stepNameBeforeEdit = activeStep.user_description ?? "";
            }}
            on:input={(e) => updateStep("user_description", e.currentTarget.value || null)}
            on:change={() => void handleCommittedStepRename()}
          />
        </Settings.Row>

        <Settings.Row title={m.flow_step_input_source_label()} description="" let:aria>
          <div class="flex flex-col gap-1.5">
            <select
              {...aria}
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              value={activeStep.input_source}
              disabled={isPublished}
              on:change={(e) => handleInputSourceChange(e.currentTarget.value as FlowStep["input_source"])}
            >
              {#each selectableInputSourceOptions as source (source.value)}
                <option value={source.value}>
                  {getInputSourceOptionLabel(source.value, source.legacyInvalid)}
                </option>
              {/each}
            </select>
            {#if INPUT_SOURCE_HINTS[activeStep.input_source]}
              <p class="text-xs text-muted leading-relaxed">{INPUT_SOURCE_HINTS[activeStep.input_source]()}</p>
            {/if}
            {#if sourceValidationMessage || inputSourceFeedback}
              <p class="text-xs leading-relaxed text-warning-stronger">
                {sourceValidationMessage ?? inputSourceFeedback}
              </p>
            {/if}
          </div>
        </Settings.Row>

        <Settings.Row title={m.flow_step_input_type()} description="" let:aria>
          <div class="flex flex-col gap-1.5">
            <select
              {...aria}
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              value={activeStep.input_type}
              disabled={isPublished}
              on:change={(e) => handleInputTypeChange(e.currentTarget.value as FlowStep["input_type"])}
            >
              {#each selectableInputTypeOptions as option (option.value)}
                <option value={option.value} disabled={option.disabled}>
                  {getInputTypeOptionLabel(option.value, option.legacyInvalid)}
                </option>
              {/each}
            </select>
            {#if inputTypeValidationMessage || inputTypeFeedback}
              <p class="text-xs leading-relaxed text-warning-stronger">
                {inputTypeValidationMessage ?? inputTypeFeedback}
              </p>
            {/if}
          </div>
        </Settings.Row>
      </Settings.Group>

      {#if activeStep.input_type === "audio"}
        <div
          class={`mb-3 rounded-lg border px-4 py-3 ${
            !transcriptionEnabled || !transcriptionModelConfigured
              ? "border-warning-default/40 bg-warning-dimmer"
              : "border-accent-default/20 bg-accent-dimmer/50"
          }`}
        >
          <div class="flex items-center justify-between">
            <div class="flex items-center gap-2.5">
              <IconMicrophone class={`size-4 shrink-0 ${
                !transcriptionEnabled || !transcriptionModelConfigured
                  ? "text-warning-stronger/70"
                  : "text-accent-default"
              }`} />
              <span class={`text-sm ${
                !transcriptionEnabled || !transcriptionModelConfigured
                  ? "text-warning-stronger"
                  : "text-primary"
              }`}>
                {#if !transcriptionEnabled}
                  {m.flow_transcription_audio_nudge()}
                {:else if !transcriptionModelConfigured}
                  {m.flow_transcription_model_label()}: <span class="text-warning-stronger font-medium">{m.no_model_selected()}</span>
                {:else}
                  {m.flow_transcription_model_label()}: <span class="font-medium">{transcriptionModelLabel ?? "—"}</span>
                {/if}
              </span>
            </div>
            <button
              class={`flex items-center gap-1 text-xs font-medium transition-colors ${
                !transcriptionEnabled || !transcriptionModelConfigured
                  ? "text-warning-stronger/80 hover:text-warning-stronger"
                  : "text-accent-default hover:text-accent-stronger"
              }`}
              on:click={() => dispatch("openTranscriptionSettings")}
            >
              {m.edit()} {m.flow_stage_transcription()}
              <IconChevronRight class="size-3.5" />
            </button>
          </div>
        </div>
      {/if}

      <!-- AI Model Section -->
      <Settings.Group title={m.completion_model()}>
        {#if activeStep.output_mode === "transcribe_only"}
          <div class="mb-4 flex items-start gap-3 rounded-lg border border-accent-default/20 border-l-4 border-l-accent-default/60 bg-accent-dimmer/60 px-4 py-3">
            <IconLockClosed class="mt-0.5 size-4 shrink-0 text-accent-default" />
            <div class="flex flex-col gap-0.5">
              <span class="text-sm font-medium text-accent-stronger">{m.flow_transcribe_only_title()}</span>
              <span class="text-xs text-accent-stronger/80">{m.flow_transcribe_only_description()}</span>
            </div>
          </div>
        {/if}
        {#if assistantLoading}
          <div class="flex items-center gap-2 px-4 py-3 text-sm text-secondary">
            <IconLoadingSpinner class="size-4 animate-spin" />
            {m.flow_step_assistant_loading()}
          </div>
        {:else if assistant}
          {@const currentAssistant = assistant}
          <div class="w-full [&>button]:w-full" class:pointer-events-none={isTranscribeOnly} class:opacity-40={isTranscribeOnly} class:saturate-[.25]={isTranscribeOnly}>
            <SelectAIModelV2
              bind:selectedModel={currentAssistant.completion_model}
              availableModels={$currentSpace.completion_models}
              on:change={() => updateAssistantField("completion_model", currentAssistant.completion_model)}
            />
          </div>

          <Settings.Row title={m.model_behaviour()} description="">
            <SelectBehaviourV2
              bind:kwArgs={currentAssistant.completion_model_kwargs}
              selectedModel={currentAssistant.completion_model}
              isDisabled={isTranscribeOnly || !supportsTemperature(currentAssistant.completion_model?.name)}
              on:change={() => updateAssistantField("completion_model_kwargs", currentAssistant.completion_model_kwargs)}
            />
          </Settings.Row>

          <Settings.Row title={m.flow_step_security_classification()} description="">
            <select
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              value={activeStep.output_classification_override ?? ""}
              disabled={isPublished}
              on:change={(e) => {
                const val = e.currentTarget.value === "" ? null : Number(e.currentTarget.value);
                updateStep("output_classification_override", val);
              }}
            >
              <option value="">{m.flow_step_security_inherit()}</option>
              <option value="1">K1</option>
              <option value="2">K2</option>
              <option value="3">K3</option>
              <option value="4">K4</option>
            </select>
          </Settings.Row>
        {/if}
      </Settings.Group>

      {#if !isTranscribeOnly}
      <!-- Knowledge Section -->
      <Settings.Group title={m.knowledge()}>
        {#if assistantLoading}
          <div class="flex items-center gap-2 px-4 py-3 text-sm text-secondary">
            <IconLoadingSpinner class="size-4 animate-spin" />
            {m.flow_step_assistant_loading()}
          </div>
        {:else if assistant}
          {@const currentAssistant = assistant}
          <Settings.Row title="" description="">
            <SelectKnowledgeV2
              originMode="personal"
              bind:selectedWebsites={currentAssistant.websites}
              bind:selectedCollections={currentAssistant.groups}
              bind:selectedIntegrationKnowledge={currentAssistant.integration_knowledge_list}
              on:change={() => {
                updateAssistantField("websites", currentAssistant.websites);
                updateAssistantField("groups", currentAssistant.groups);
                updateAssistantField("integration_knowledge_list", currentAssistant.integration_knowledge_list);
              }}
            />
            <SelectKnowledgeV2
              originMode="organization"
              bind:selectedWebsites={currentAssistant.websites}
              bind:selectedCollections={currentAssistant.groups}
              bind:selectedIntegrationKnowledge={currentAssistant.integration_knowledge_list}
              on:change={() => {
                updateAssistantField("websites", currentAssistant.websites);
                updateAssistantField("groups", currentAssistant.groups);
                updateAssistantField("integration_knowledge_list", currentAssistant.integration_knowledge_list);
              }}
            />
          </Settings.Row>
        {/if}
      </Settings.Group>

      <!-- Attachments Section -->
      <Settings.Group title={m.attachments()}>
        {#if assistantLoading}
          <div class="flex items-center gap-2 px-4 py-3 text-sm text-secondary">
            <IconLoadingSpinner class="size-4 animate-spin" />
            {m.flow_step_assistant_loading()}
          </div>
        {:else if assistant}
          <Settings.Row title="" description="">
            <div class="w-full">
              {#each (Array.isArray(assistant.attachments) ? assistant.attachments : []) as file (file.id)}
                <div class="border-default bg-primary hover:bg-hover-dimmer flex h-16 items-center gap-3 border-b px-4">
                  <UploadedFileIcon {file}></UploadedFileIcon>
                  <div class="flex flex-grow items-center justify-between gap-1">
                    <AttachmentPreview {file} isTableView={true}>
                      {#snippet children({ showFile }: { showFile: () => void })}
                        <button
                          on:click={showFile}
                          class="line-clamp-1 cursor-pointer text-left hover:underline"
                        >
                          {file.name}
                        </button>
                      {/snippet}
                    </AttachmentPreview>
                    <span class="text-secondary line-clamp-1 text-right text-sm">
                      {formatFileType(file.mimetype)} · {formatBytes(file.size)}
                    </span>
                  </div>
                  <div class="min-w-8">
                    <Button variant="destructive" padding="icon" on:click={() => void removeAttachment(file)}>
                      <IconTrash></IconTrash>
                    </Button>
                  </div>
                </div>
              {/each}

              {#each runningUploads as upload (upload.id)}
                <div class="border-default bg-primary hover:bg-hover-dimmer flex h-16 w-full items-center gap-4 border-b px-4">
                  <UploadedFileIcon file={{ mimetype: upload.file.type }}></UploadedFileIcon>
                  <div class="flex flex-grow flex-col gap-1">
                    <div class="flex max-w-full items-center gap-4">
                      <span class="line-clamp-1 flex-grow font-medium">{upload.file.name}</span>
                      <span class="text-secondary line-clamp-1 text-right text-sm">
                        {formatFileType(upload.file.type)} · {formatBytes(upload.file.size)}
                      </span>
                    </div>
                    <div class="h-1.5 w-full overflow-hidden rounded-full bg-hover-dimmer">
                      <div class="h-full bg-accent-default transition-all" style={`width: ${upload.progress}%`}></div>
                    </div>
                  </div>
                  <div class="min-w-8">
                    <Button variant="destructive" padding="icon" on:click={() => upload.remove()}>
                      <IconCancel />
                    </Button>
                  </div>
                </div>
              {/each}
              <div class="mt-2">
                <AttachmentUploadTextButton multiple></AttachmentUploadTextButton>
              </div>
            </div>
          </Settings.Row>
        {/if}
      </Settings.Group>

      <!-- Instruction Section -->
      <Settings.Group title={m.instructions()}>
        <Settings.Row title={m.instructions()} description={m.flow_step_instructions_desc()} fullWidth>
          <svelte:fragment slot="title">
            <Tooltip text={m.flow_step_instructions_tooltip()}>
              <IconQuestionMark class="ml-1.5 text-muted hover:text-primary" />
            </Tooltip>
          </svelte:fragment>
          <FlowPromptEditor
            value={instructionText}
            disabled={isPublished || assistantLoading || !assistant}
            placeholder={m.flow_step_instructions_placeholder()}
            {steps}
            currentStepOrder={activeStep.step_order}
            {formSchema}
            transcriptionEnabled={transcriptionEnabled && hasAudioInputSteps}
            {isAdvancedMode}
            on:change={(e) => {
              if (assistant?.prompt) {
                assistant = { ...assistant, prompt: { ...assistant.prompt, text: e.detail } };
              }
            }}
            on:commit={(e) => updateInstruction(e.detail)}
          >
            <svelte:fragment slot="toolbar">
              {#if assistant?.id && !isPublished}
                <PromptVersionDialog
                  title={m.prompt_history()}
                  loadPromptVersionHistory={() => {
                    return flowEditor.listAssistantPrompts(activeStep.assistant_id);
                  }}
                  onPromptSelected={(prompt) => {
                    if (assistant?.prompt) {
                      updateAssistantField("prompt", { ...assistant.prompt, text: prompt.text });
                    }
                  }}
                />
              {/if}
            </svelte:fragment>
          </FlowPromptEditor>
        </Settings.Row>
      </Settings.Group>
      {/if}

      {#if !isTranscribeOnly}
        {#if $mode !== "power_user" && hasInputTemplateOverride}
          <div class="mb-3 flex items-start gap-3 rounded-lg border border-warning-default/40 bg-warning-dimmer px-3 py-2.5 text-xs text-warning-stronger">
            <span class="flex-1">{m.flow_input_template_override_warning()}</span>
            <Button variant="outlined" size="small" on:click={() => updateInputTemplate("")}>
              {m.clear()}
            </Button>
          </div>
        {/if}

        {#if templateSourceConflict && $mode === "power_user"}
          <div class="mb-3 flex items-start gap-3 rounded-lg border border-warning-default/40 bg-warning-dimmer px-3 py-2.5 text-xs text-warning-stronger">
            <span class="flex-1">
              {m.flow_template_source_conflict_warning({
                steps: templateSourceConflict.map((n) => `Step ${n}`).join(", "),
                source: INPUT_SOURCE_LABELS[activeStep.input_source]?.() ?? activeStep.input_source
              })}
            </span>
            <div class="flex shrink-0 gap-1.5">
              {#if activeStep.input_source === "flow_input" && templateStepRefs.length === 1 && templateStepRefs[0] === activeStep.step_order - 1}
                <Button variant="outlined" size="small"
                  on:click={() => handleInputSourceChange("previous_step")}
                >{m.flow_template_source_conflict_fix_source()}</Button>
              {/if}
              <Button variant="outlined" size="small"
                on:click={() => updateInputTemplate("")}
              >{m.flow_template_source_conflict_fix_clear()}</Button>
            </div>
          </div>
        {/if}

        <!-- Custom Input Section (Power User for all sources) -->
        {#if showInputTemplate}
          <div transition:slide={{ duration: 200 }}>
          <Settings.Group title={m.flow_step_input_template()}>
            <Settings.Row title={m.flow_step_input_template()} description={m.flow_step_input_template_desc()}>
              <svelte:fragment slot="title">
                <Tooltip text={m.flow_step_input_template_tooltip()}>
                  <IconQuestionMark class="ml-1.5 text-muted hover:text-primary" />
                </Tooltip>
              </svelte:fragment>
              <FlowPromptEditor
                value={inputTemplateText}
                disabled={isPublished}
                placeholder={m.flow_step_input_template_placeholder()}
                {steps}
                currentStepOrder={activeStep.step_order}
                {formSchema}
                transcriptionEnabled={transcriptionEnabled && hasAudioInputSteps}
                isAdvancedMode={true}
                on:change={(e) => updateInputTemplate(e.detail)}
              />
            </Settings.Row>
          </Settings.Group>
          </div>
        {/if}
      {/if}

      <!-- Output Section -->
      <Settings.Group title={m.flow_step_output_section()}>
        <Settings.Row title={m.flow_step_output_type()} description="">
          <select
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            value={activeStep.output_type}
            disabled={isPublished}
            on:change={(e) => updateStep("output_type", e.currentTarget.value)}
          >
            {#each availableOutputTypes as t (t.value)}
              <option value={t.value}>{t.label}</option>
            {/each}
          </select>
        </Settings.Row>

        <Settings.Row title={m.flow_step_output_mode()} description="">
          <select
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            value={activeStep.output_mode}
            disabled={isPublished}
            on:change={(e) => handleOutputModeChange(e.currentTarget.value as FlowStep["output_mode"])}
          >
            {#each availableOutputModes as mode (mode.value)}
              <option value={mode.value}>{mode.label}</option>
            {/each}
          </select>
        </Settings.Row>

        {#if activeStep.output_mode === "http_post"}
          <Settings.Row title={m.flow_step_webhook_url()} description="">
            <input
              type="url"
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              value={activeStep.output_config?.url ?? ""}
              disabled={isPublished}
              on:input={(e) => {
                updateStep("output_config", { ...(activeStep?.output_config ?? {}), url: e.currentTarget.value });
              }}
              placeholder="https://..."
            />
          </Settings.Row>
        {/if}
      </Settings.Group>

      <!-- Typed I/O info banners -->
      {#if activeStep.output_type === "json" && activeStep.output_contract}
        <div class="flex items-start gap-2 mb-3 rounded-lg border border-accent-default/30 bg-accent-dimmer px-3 py-2.5 text-xs text-accent-stronger">
          {m.flow_typed_io_json_contract_info()}
        </div>
      {/if}

      {#if (activeStep.output_type === "pdf" || activeStep.output_type === "docx") && activeStep.output_contract}
        <div class="flex items-start gap-2 mb-3 rounded-lg border border-accent-default/30 bg-accent-dimmer px-3 py-2.5 text-xs text-accent-stronger">
          {m.flow_typed_io_doc_contract_info()}
        </div>
      {/if}

      {#if activeStep.input_type === "document" && activeStep.step_order === 1}
        <div class="flex items-start gap-2 mb-3 rounded-lg border border-accent-default/30 bg-accent-dimmer px-3 py-2.5 text-xs text-accent-stronger">
          {m.flow_typed_io_document_input_info()}
        </div>
      {/if}

      {#if activeStep.input_type === "image"}
        <div class="flex items-start gap-2 mb-3 rounded-lg border border-warning-default/40 bg-warning-dimmer px-3 py-2.5 text-xs text-warning-stronger">
          {m.flow_typed_io_image_not_supported()}
        </div>
      {/if}

      <!-- Advanced Section (Power User only) -->
      {#if isAdvancedMode}
        <div transition:slide={{ duration: 200 }} class="border-l border-l-amber-300/50">
        <Settings.Group title={m.flow_step_advanced()}>
          <Settings.Row title={m.flow_step_mcp_policy()} description="">
            <svelte:fragment slot="title">
              <Tooltip text={m.flow_step_mcp_policy_tooltip()}>
                <IconQuestionMark class="ml-1.5 text-muted hover:text-primary" />
              </Tooltip>
            </svelte:fragment>
            <select
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              value={activeStep.mcp_policy}
              disabled={isPublished}
              on:change={(e) => updateStep("mcp_policy", e.currentTarget.value)}
            >
              {#each MCP_POLICIES as policy (policy.value)}
                <option value={policy.value}>{policy.label}</option>
              {/each}
            </select>
          </Settings.Row>

          <Settings.Row title={m.flow_step_input_contract()} description={m.flow_step_input_contract_desc()}>
            <svelte:fragment slot="title">
              <Tooltip text={m.flow_step_input_contract_tooltip()}>
                <IconQuestionMark class="ml-1.5 text-muted hover:text-primary" />
              </Tooltip>
            </svelte:fragment>
            <textarea
              class="border-default bg-primary ring-default min-h-[80px] w-full rounded-lg border px-3 py-2 font-mono text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              value={advancedJsonDrafts.input_contract}
              disabled={isPublished}
              on:input={(e) => updateAdvancedJsonField("input_contract", e.currentTarget.value)}
              placeholder={'{"type": "object", "properties": {...}}'}
            ></textarea>
            {#if advancedJsonErrors.input_contract}
              <p class="mt-1 text-xs text-warning-stronger" role="alert">{advancedJsonErrors.input_contract}</p>
            {/if}
          </Settings.Row>

          <Settings.Row title={m.flow_step_output_contract()} description={m.flow_step_output_contract_desc()}>
            <svelte:fragment slot="title">
              <Tooltip text={m.flow_step_output_contract_tooltip()}>
                <IconQuestionMark class="ml-1.5 text-muted hover:text-primary" />
              </Tooltip>
            </svelte:fragment>
            <textarea
              class="border-default bg-primary ring-default min-h-[80px] w-full rounded-lg border px-3 py-2 font-mono text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              value={advancedJsonDrafts.output_contract}
              disabled={isPublished}
              on:input={(e) => updateAdvancedJsonField("output_contract", e.currentTarget.value)}
              placeholder={'{"type": "object", "properties": {...}}'}
            ></textarea>
            {#if advancedJsonErrors.output_contract}
              <p class="mt-1 text-xs text-warning-stronger" role="alert">{advancedJsonErrors.output_contract}</p>
            {/if}
          </Settings.Row>

          {#if activeStep.input_source === "http_get" || activeStep.input_source === "http_post"}
            <Settings.Row title={m.flow_step_input_config()} description={m.flow_step_input_config_desc()}>
              <textarea
                class="border-default bg-primary ring-default min-h-[80px] w-full rounded-lg border px-3 py-2 font-mono text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                value={advancedJsonDrafts.input_config}
                disabled={isPublished}
                on:input={(e) => updateAdvancedJsonField("input_config", e.currentTarget.value)}
                placeholder={'{"url": "https://...", "headers": {...}}'}
              ></textarea>
              {#if advancedJsonErrors.input_config}
                <p class="mt-1 text-xs text-warning-stronger" role="alert">{advancedJsonErrors.input_config}</p>
              {/if}
            </Settings.Row>
          {/if}

          {#if activeStep.output_mode === "http_post"}
            <Settings.Row title={m.flow_step_output_config()} description={m.flow_step_output_config_desc()}>
              <textarea
                class="border-default bg-primary ring-default min-h-[80px] w-full rounded-lg border px-3 py-2 font-mono text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                value={advancedJsonDrafts.output_config}
                disabled={isPublished}
                on:input={(e) => updateAdvancedJsonField("output_config", e.currentTarget.value)}
                placeholder={'{"url": "https://...", "headers": {...}}'}
              ></textarea>
              {#if advancedJsonErrors.output_config}
                <p class="mt-1 text-xs text-warning-stronger" role="alert">{advancedJsonErrors.output_config}</p>
              {/if}
            </Settings.Row>
          {/if}
        </Settings.Group>
        </div>
      {/if}

      <!-- Delete Step -->
      {#if !isPublished}
        <div class="mt-8 border-t border-default pt-4">
          <Button variant="destructive" class="w-full justify-center rounded-lg" on:click={() => { $showDeleteConfirm = true; }}>
            <IconTrash size="sm" />
            {m.flow_step_remove()}
          </Button>
        </div>
      {/if}
    </Settings.Page>
    </div>
  </div>
{/if}

<Dialog.Root alert bind:isOpen={showDeleteConfirm}>
  <Dialog.Content width="small">
    <div class="mb-3 flex justify-center">
      <svg class="size-10 text-negative-default/60" viewBox="0 0 24 24" fill="none" stroke="currentColor"
        stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round">
        <circle cx="12" cy="12" r="10"/>
        <line x1="12" y1="8" x2="12" y2="12"/>
        <line x1="12" y1="16" x2="12.01" y2="16"/>
      </svg>
    </div>
    <Dialog.Title>{m.flow_step_remove()}</Dialog.Title>
    <Dialog.Description>{m.flow_step_remove_confirm()}</Dialog.Description>
    <Dialog.Controls let:close>
      <Button variant="simple" is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={() => {
        if (activeIndex >= 0) {
          dispatch("removeStep", activeIndex);
          $showDeleteConfirm = false;
        }
      }}>{m.delete()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
