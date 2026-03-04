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
  import { Button, Dialog, Tooltip } from "@intric/ui";
  import { toast } from "$lib/components/toast";
  import { m } from "$lib/paraglide/messages";
  import { slide } from "svelte/transition";

  export let steps: FlowStep[];
  export let activeStepId: string | null;
  export let isPublished: boolean;
  export let transcriptionEnabled: boolean = true;
  export let formSchema: { fields: { name: string; type: string; required?: boolean; options?: string[]; order?: number }[] } | undefined;

  const dispatch = createEventDispatcher<{
    stepChanged: { index: number; step: FlowStep };
    removeStep: number;
    jsonValidationChanged: { hasErrors: boolean; fields: string[] };
  }>();

  const mode = getFlowUserMode();
  const flowEditor = getFlowEditor();
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
  let assistant: any = null;
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

  // Load assistant when active step changes
  $: if (activeStep?.assistant_id && activeStep.assistant_id !== lastLoadedAssistantId) {
    cancelUploadsAndClearQueue();
    void loadAssistantForStep(activeStep.assistant_id);
  } else if (!activeStep || !activeStep.assistant_id) {
    assistant = null;
    lastLoadedAssistantId = null;
    assistantLoading = false;
    cancelUploadsAndClearQueue();
  }

  onDestroy(() => {
    cancelUploadsAndClearQueue();
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
      if (requestToken !== assistantLoadRequestToken) return;
      assistantLoading = false;
    }
  }

  function updateInstruction(value: string) {
    if (!activeStep?.assistant_id) return;
    const currentPrompt =
      assistant && typeof assistant === "object" && assistant.prompt && typeof assistant.prompt === "object"
        ? assistant.prompt
        : { text: "", description: "" };
    const currentText = typeof currentPrompt.text === "string" ? currentPrompt.text : "";
    if (value === currentText) return;
    const nextPrompt = { ...currentPrompt, text: value, description: "" };
    assistant = { ...(assistant ?? {}), prompt: nextPrompt };
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
    const httpSourceSelected = nextSource === "http_get" || nextSource === "http_post";
    const unsupportedHttpInputType =
      activeStep.input_type === "document" ||
      activeStep.input_type === "file" ||
      activeStep.input_type === "image" ||
      activeStep.input_type === "audio";
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
    const updated = {
      ...activeStep,
      input_source: nextSource,
      input_type:
        (nextSource !== "flow_input" && activeStep.input_type === "document") || (httpSourceSelected && unsupportedHttpInputType)
          ? "text"
          : activeStep.input_type,
      input_config: nextInputConfig,
      input_bindings: sanitizeBindingsForSource(
        activeStep.input_bindings as Record<string, unknown> | null | undefined
      )
    };
    dispatch("stepChanged", { index: activeIndex, step: updated });
  }

  function handleInputTypeChange(nextType: FlowStep["input_type"]) {
    if (activeStep === null || activeIndex < 0) return;
    const updated = {
      ...activeStep,
      input_type: nextType,
      input_source:
        nextType === "document" && activeStep.input_source !== "flow_input"
          ? "flow_input"
          : activeStep.input_source
    };
    dispatch("stepChanged", { index: activeIndex, step: updated });
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
  $: assistantSecurityLevel =
    assistant &&
    typeof assistant === "object" &&
    assistant.completion_model &&
    typeof assistant.completion_model === "object" &&
    assistant.completion_model.security_classification &&
    typeof assistant.completion_model.security_classification === "object" &&
    typeof assistant.completion_model.security_classification.security_level === "number"
      ? assistant.completion_model.security_classification.security_level
      : null;
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
    assistant = { ...assistant, [field]: value };
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

  // Type chain compatibility (matching backend _COMPATIBLE_COERCIONS)
  const COMPATIBLE_COERCIONS = new Set([
    "text:text", "text:json", "text:any",
    "json:text", "json:json", "json:any",
    "pdf:text", "pdf:any",
    "docx:text", "docx:any",
  ]);

  $: previousStep = activeStep && activeStep.step_order > 1
    ? steps.find((s) => s.step_order === activeStep!.step_order - 1)
    : null;

  $: typeChainIncompatible = (() => {
    if (!activeStep || activeStep.input_source !== "previous_step" || !previousStep) return false;
    const key = `${previousStep.output_type}:${activeStep.input_type}`;
    return !COMPATIBLE_COERCIONS.has(key);
  })();

  const INPUT_SOURCES = [
    { value: "flow_input", get label() { return m.flow_input_source_flow_input(); } },
    { value: "previous_step", get label() { return m.flow_input_source_previous_step(); } },
    { value: "all_previous_steps", get label() { return m.flow_input_source_all_previous_steps(); } },
    { value: "http_get", get label() { return m.flow_input_source_http_get(); } },
    { value: "http_post", get label() { return m.flow_input_source_http_post(); } }
  ];

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

  const INPUT_SOURCE_HINTS: Record<string, () => string> = {
    flow_input: () => m.flow_input_source_hint_flow_input(),
    previous_step: () => m.flow_input_source_hint_previous_step(),
    all_previous_steps: () => m.flow_input_source_hint_all_previous_steps(),
  };
  const OUTPUT_MODES = [
    { value: "pass_through", get label() { return m.flow_output_mode_pass_through(); } },
    { value: "http_post", get label() { return m.flow_output_mode_http_post(); } }
  ];
  const MCP_POLICIES = [
    { value: "inherit", get label() { return m.flow_mcp_policy_inherit(); } },
    { value: "restricted", get label() { return m.flow_mcp_policy_restricted(); } }
  ];

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
              {#each INPUT_SOURCES as source}
                <option value={source.value}>
                  {source.label}
                </option>
              {/each}
            </select>
            {#if INPUT_SOURCE_HINTS[activeStep.input_source]}
              <p class="text-xs text-muted leading-relaxed">{INPUT_SOURCE_HINTS[activeStep.input_source]()}</p>
            {/if}
          </div>
        </Settings.Row>

        <Settings.Row title={m.flow_step_input_type()} description="" let:aria>
          <select
            {...aria}
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            value={activeStep.input_type}
            disabled={isPublished}
            on:change={(e) => handleInputTypeChange(e.currentTarget.value as FlowStep["input_type"])}
          >
            {#each INPUT_TYPES as t}
              <option value={t.value}>{t.label}</option>
            {/each}
          </select>
        </Settings.Row>
      </Settings.Group>

      <!-- AI Model Section -->
      <Settings.Group title={m.completion_model()}>
        {#if assistantLoading}
          <div class="flex items-center gap-2 px-4 py-3 text-sm text-secondary">
            <IconLoadingSpinner class="size-4 animate-spin" />
            {m.flow_step_assistant_loading()}
          </div>
        {:else if assistant}
          <Settings.Row title={m.completion_model()} description="">
            <SelectAIModelV2
              bind:selectedModel={assistant.completion_model}
              availableModels={$currentSpace.completion_models}
              on:change={() => updateAssistantField("completion_model", assistant.completion_model)}
            />
          </Settings.Row>

          <Settings.Row title={m.model_behaviour()} description="">
            <SelectBehaviourV2
              bind:kwArgs={assistant.completion_model_kwargs}
              selectedModel={assistant.completion_model}
              isDisabled={!supportsTemperature(assistant.completion_model?.name)}
              on:change={() => updateAssistantField("completion_model_kwargs", assistant.completion_model_kwargs)}
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

      <!-- Knowledge Section -->
      <Settings.Group title={m.knowledge()}>
        {#if assistantLoading}
          <div class="flex items-center gap-2 px-4 py-3 text-sm text-secondary">
            <IconLoadingSpinner class="size-4 animate-spin" />
            {m.flow_step_assistant_loading()}
          </div>
        {:else if assistant}
          <Settings.Row title="" description="" let:aria>
            <SelectKnowledgeV2
              originMode="personal"
              bind:selectedWebsites={assistant.websites}
              bind:selectedCollections={assistant.groups}
              bind:selectedIntegrationKnowledge={assistant.integration_knowledge_list}
              on:change={() => {
                updateAssistantField("websites", assistant.websites);
                updateAssistantField("groups", assistant.groups);
                updateAssistantField("integration_knowledge_list", assistant.integration_knowledge_list);
              }}
            />
            <SelectKnowledgeV2
              originMode="organization"
              bind:selectedWebsites={assistant.websites}
              bind:selectedCollections={assistant.groups}
              bind:selectedIntegrationKnowledge={assistant.integration_knowledge_list}
              on:change={() => {
                updateAssistantField("websites", assistant.websites);
                updateAssistantField("groups", assistant.groups);
                updateAssistantField("integration_knowledge_list", assistant.integration_knowledge_list);
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
            {transcriptionEnabled}
            isAdvancedMode={$mode === "power_user"}
            on:change={(e) => {
              const currentPrompt = assistant?.prompt ?? { text: "", description: "" };
              assistant = { ...(assistant ?? {}), prompt: { ...currentPrompt, text: e.detail } };
            }}
            on:commit={(e) => updateInstruction(e.detail)}
          >
            <svelte:fragment slot="toolbar">
              {#if assistant?.id && !isPublished}
                <PromptVersionDialog
                  title={m.prompt_history()}
                  loadPromptVersionHistory={() => {
                    return flowEditor.listAssistantPrompts(activeStep.assistant_id) as Promise<any[]>;
                  }}
                  onPromptSelected={(prompt) => {
                    updateAssistantField("prompt", { ...assistant.prompt, text: prompt.text });
                  }}
                />
              {/if}
            </svelte:fragment>
          </FlowPromptEditor>
        </Settings.Row>
      </Settings.Group>

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
              {transcriptionEnabled}
              isAdvancedMode={true}
              on:change={(e) => updateInputTemplate(e.detail)}
            />
          </Settings.Row>
        </Settings.Group>
        </div>
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
            {#each OUTPUT_TYPES as t}
              <option value={t.value}>{t.label}</option>
            {/each}
          </select>
        </Settings.Row>

        <Settings.Row title={m.flow_step_output_mode()} description="">
          <select
            class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            value={activeStep.output_mode}
            disabled={isPublished}
            on:change={(e) => updateStep("output_mode", e.currentTarget.value)}
          >
            {#each OUTPUT_MODES as mode}
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

      {#if activeStep.input_type === "audio"}
        <div class="flex items-start gap-2 mb-3 rounded-lg border border-warning-default/40 bg-warning-dimmer px-3 py-2.5 text-xs text-warning-stronger">
          {m.flow_typed_io_audio_not_supported()}
        </div>
      {/if}

      {#if activeStep.input_type === "image"}
        <div class="flex items-start gap-2 mb-3 rounded-lg border border-warning-default/40 bg-warning-dimmer px-3 py-2.5 text-xs text-warning-stronger">
          {m.flow_typed_io_image_not_supported()}
        </div>
      {/if}

      {#if typeChainIncompatible && previousStep}
        <div class="flex items-start gap-2 mb-3 rounded-lg border border-warning-default/40 bg-warning-dimmer px-3 py-2.5 text-xs text-warning-stronger">
          {m.flow_typed_io_chain_incompatible({
            outputType: previousStep.output_type,
            inputType: activeStep.input_type,
            prevStep: String(previousStep.step_order),
          })}
        </div>
      {/if}

      <!-- Advanced Section (Power User only) -->
      {#if $mode === "power_user"}
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
              {#each MCP_POLICIES as policy}
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
