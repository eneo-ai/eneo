<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { Settings } from "$lib/components/layout";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { getFlowEditor } from "$lib/features/flows/FlowEditor";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import VariablePicker from "./VariablePicker.svelte";
  import FlowVariableChipPreview from "./FlowVariableChipPreview.svelte";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectBehaviourV2 from "$lib/features/ai-models/components/SelectBehaviourV2.svelte";
  import SelectKnowledgeV2 from "$lib/features/knowledge/components/SelectKnowledgeV2.svelte";
  import { supportsTemperature } from "$lib/features/ai-models/supportsTemperature.js";
  import PromptVersionDialog from "$lib/features/prompts/components/PromptVersionDialog.svelte";
  import FlowFormSchemaEditor from "./FlowFormSchemaEditor.svelte";
  import { createEventDispatcher } from "svelte";
  import { IconTrash } from "@intric/icons/trash";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconWorkflow } from "@intric/icons/workflow";
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { Button, Dialog, Tooltip } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";
  import { slide } from "svelte/transition";

  export let steps: FlowStep[];
  export let activeStepId: string | null;
  export let isPublished: boolean;
  export let formSchema: { fields: { name: string; type: string; required?: boolean }[] } | undefined;

  const dispatch = createEventDispatcher<{
    stepChanged: { index: number; step: FlowStep };
    removeStep: number;
  }>();

  const mode = getFlowUserMode();
  const flowEditor = getFlowEditor();
  const { state: { currentSpace } } = getSpacesManager();

  $: activeIndex = steps.findIndex((s) => s.id === activeStepId);
  $: activeStep = activeIndex >= 0 ? steps[activeIndex] : null;

  // Assistant state for the active step
  let assistant: any = null;
  let assistantLoading = false;
  let lastLoadedAssistantId: string | null = null;
  const autoClearedLegacyTemplateByStepId = new Set<string>();

  // Load assistant when active step changes
  $: if (activeStep?.assistant_id && activeStep.assistant_id !== lastLoadedAssistantId) {
    void loadAssistantForStep(activeStep.assistant_id);
  } else if (!activeStep || !activeStep.assistant_id) {
    assistant = null;
    lastLoadedAssistantId = null;
    assistantLoading = false;
  }

  async function loadAssistantForStep(assistantId: string) {
    if (!assistantId || assistantId === "") return;
    assistantLoading = true;
    lastLoadedAssistantId = assistantId;
    try {
      assistant = await flowEditor.loadAssistant(assistantId);
    } catch {
      assistant = null;
    } finally {
      assistantLoading = false;
    }
  }

  function updateInstruction(value: string) {
    if (!activeStep?.assistant_id) return;
    const currentPrompt =
      assistant && typeof assistant === "object" && assistant.prompt && typeof assistant.prompt === "object"
        ? assistant.prompt
        : { text: "", description: "" };
    const nextPrompt = { ...currentPrompt, text: value, description: "" };
    assistant = { ...(assistant ?? {}), prompt: nextPrompt };
    flowEditor.saveAssistant(activeStep.assistant_id, { prompt: nextPrompt });
  }

  function sanitizeBindingsForSource(
    bindings: Record<string, unknown> | null | undefined
  ): Record<string, unknown> | null {
    const nextBindings: Record<string, unknown> = { ...(bindings ?? {}) };
    delete nextBindings.text;
    return Object.keys(nextBindings).length > 0 ? nextBindings : null;
  }

  function handleInputSourceChange(nextSource: string) {
    if (activeStep === null || activeIndex < 0) return;
    const updated = {
      ...activeStep,
      input_source: nextSource,
      input_bindings: sanitizeBindingsForSource(
        activeStep.input_bindings as Record<string, unknown> | null | undefined
      )
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
  $: showInputTemplate = $mode === "power_user";
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

  const INPUT_SOURCE_LABELS: Record<string, () => string> = {
    flow_input: () => m.flow_input_source_flow_input(),
    previous_step: () => m.flow_input_source_previous_step(),
    all_previous_steps: () => m.flow_input_source_all_previous_steps()
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

  // Type chain compatibility (matching backend _COMPATIBLE_COERCIONS)
  const COMPATIBLE_COERCIONS = new Set([
    "text:text", "text:json", "text:any",
    "json:text", "json:json", "json:any",
    "pdf:text", "pdf:document", "pdf:any",
    "docx:text", "docx:document", "docx:any",
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
    { value: "http_get", get label() { return m.flow_input_source_http_get(); }, disabled: true },
    { value: "http_post", get label() { return m.flow_input_source_http_post(); }, disabled: true }
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
    <!-- Flow settings (form schema editor) -->
    <div class="p-6" class:pointer-events-none={isPublished} class:opacity-60={isPublished}>
      <Settings.Page>
        <FlowFormSchemaEditor {isPublished} />
      </Settings.Page>
    </div>
  {/if}
{:else}
  <div class="p-4 lg:p-6" class:pointer-events-none={isPublished} class:opacity-60={isPublished}>
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
            on:input={(e) => updateStep("user_description", e.currentTarget.value || null)}
          />
        </Settings.Row>

        <Settings.Row title={m.flow_step_input_source_label()} description="" let:aria>
          <div class="flex flex-col gap-1.5">
            <select
              {...aria}
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              value={activeStep.input_source}
              disabled={isPublished}
              on:change={(e) => handleInputSourceChange(e.currentTarget.value)}
            >
              {#each INPUT_SOURCES as source}
                <option value={source.value} disabled={source.disabled ?? false}>
                  {source.label}{source.disabled ? ` (${m.flow_coming_soon()})` : ""}
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
            on:change={(e) => updateStep("input_type", e.currentTarget.value)}
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

      <!-- Instruction Section -->
      <Settings.Group title={m.instructions()}>
        <Settings.Row title={m.instructions()} description={m.describe_assistant_behavior()} fullWidth let:aria>
          <div slot="toolbar" class="text-secondary">
            {#if assistant?.id && !isPublished}
              <PromptVersionDialog
                title={m.prompt_history()}
                loadPromptVersionHistory={() => {
                  return flowEditor.listAssistantPrompts(activeStep.assistant_id);
                }}
                onPromptSelected={(prompt) => {
                  updateAssistantField("prompt", { ...assistant.prompt, text: prompt.text });
                }}
              />
            {/if}
          </div>
          <textarea
            {...aria}
            class="border-default bg-primary ring-default min-h-[120px] w-full rounded-lg border px-4 py-3 font-mono text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
            value={instructionText}
            disabled={isPublished || assistantLoading || !assistant}
            on:input={(e) => updateInstruction(e.currentTarget.value)}
            placeholder={m.flow_step_instructions_placeholder()}
          ></textarea>
        </Settings.Row>
      </Settings.Group>

      {#if $mode !== "power_user" && hasInputTemplateOverride}
        <div class="mb-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-800">
          <span class="flex-1">{m.flow_input_template_override_warning()}</span>
          <Button variant="outlined" size="small" on:click={() => updateInputTemplate("")}>
            {m.clear()}
          </Button>
        </div>
      {/if}

      {#if templateSourceConflict && $mode === "power_user"}
        <div class="mb-4 flex items-start gap-3 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300">
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
            <div class="flex flex-col gap-1.5">
              <FlowVariableChipPreview
                text={inputTemplateText}
                {steps}
                compact
              />

              <!-- Toolbar + textarea editor -->
              <div class="border-default overflow-hidden rounded-lg border shadow">
                <div class="bg-secondary/50 flex items-center justify-between border-b border-default px-3 py-1.5">
                  <span class="text-[11px] text-muted">{m.flow_variable_toolbar_hint()}</span>
                  {#if !isPublished}
                    <VariablePicker
                      {steps}
                      currentStepOrder={activeStep.step_order}
                      {formSchema}
                      on:insert={(e) => {
                        updateInputTemplate(`${inputTemplateText}${e.detail}`);
                      }}
                    />
                  {/if}
                </div>
                <textarea
                  class="bg-primary min-h-[100px] w-full resize-y px-3 py-2 font-mono text-sm focus:outline-none"
                  value={inputTemplateText}
                  disabled={isPublished}
                  on:input={(e) => updateInputTemplate(e.currentTarget.value)}
                  placeholder={m.flow_step_input_template_placeholder()}
                ></textarea>
              </div>
            </div>
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
        <div class="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2.5 text-xs text-blue-800 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300">
          {m.flow_typed_io_json_contract_info()}
        </div>
      {/if}

      {#if (activeStep.output_type === "pdf" || activeStep.output_type === "docx") && activeStep.output_contract}
        <div class="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2.5 text-xs text-blue-800 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300">
          {m.flow_typed_io_doc_contract_info()}
        </div>
      {/if}

      {#if activeStep.input_type === "document" && activeStep.step_order === 1}
        <div class="flex items-start gap-2 rounded-lg border border-blue-200 bg-blue-50 px-3 py-2.5 text-xs text-blue-800 dark:border-blue-800 dark:bg-blue-950 dark:text-blue-300">
          {m.flow_typed_io_document_input_info()}
        </div>
      {/if}

      {#if activeStep.input_type === "audio"}
        <div class="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300">
          {m.flow_typed_io_audio_not_supported()}
        </div>
      {/if}

      {#if activeStep.input_type === "image"}
        <div class="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300">
          {m.flow_typed_io_image_not_supported()}
        </div>
      {/if}

      {#if typeChainIncompatible && previousStep}
        <div class="flex items-start gap-2 rounded-lg border border-amber-200 bg-amber-50 px-3 py-2.5 text-xs text-amber-800 dark:border-amber-800 dark:bg-amber-950 dark:text-amber-300">
          {m.flow_typed_io_chain_incompatible({
            outputType: previousStep.output_type,
            inputType: activeStep.input_type,
            prevStep: String(previousStep.step_order),
          })}
        </div>
      {/if}

      <!-- Advanced Section (Power User only) -->
      {#if $mode === "power_user"}
        <div transition:slide={{ duration: 200 }}>
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

          <Settings.Row title={m.flow_step_classification_override()} description="">
            <svelte:fragment slot="title">
              <Tooltip text={m.flow_step_classification_override_tooltip()}>
                <IconQuestionMark class="ml-1.5 text-muted hover:text-primary" />
              </Tooltip>
            </svelte:fragment>
            <input
              type="number"
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              value={activeStep.output_classification_override ?? ""}
              disabled={isPublished}
              on:input={(e) => {
                const val = e.currentTarget.value ? Number(e.currentTarget.value) : null;
                updateStep("output_classification_override", val);
              }}
              placeholder={m.flow_step_leave_empty_for_default()}
            />
          </Settings.Row>

          <Settings.Row title={m.flow_step_input_contract()} description={m.flow_step_input_contract_desc()}>
            <svelte:fragment slot="title">
              <Tooltip text={m.flow_step_input_contract_tooltip()}>
                <IconQuestionMark class="ml-1.5 text-muted hover:text-primary" />
              </Tooltip>
            </svelte:fragment>
            <textarea
              class="border-default bg-primary ring-default min-h-[80px] w-full rounded-lg border px-3 py-2 font-mono text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              value={activeStep.input_contract ? JSON.stringify(activeStep.input_contract, null, 2) : ""}
              disabled={isPublished}
              on:input={(e) => {
                try {
                  const val = e.currentTarget.value.trim() ? JSON.parse(e.currentTarget.value) : null;
                  updateStep("input_contract", val);
                } catch { /* ignore parse errors while typing */ }
              }}
              placeholder={'{"type": "object", "properties": {...}}'}
            ></textarea>
          </Settings.Row>

          <Settings.Row title={m.flow_step_output_contract()} description={m.flow_step_output_contract_desc()}>
            <svelte:fragment slot="title">
              <Tooltip text={m.flow_step_output_contract_tooltip()}>
                <IconQuestionMark class="ml-1.5 text-muted hover:text-primary" />
              </Tooltip>
            </svelte:fragment>
            <textarea
              class="border-default bg-primary ring-default min-h-[80px] w-full rounded-lg border px-3 py-2 font-mono text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              value={activeStep.output_contract ? JSON.stringify(activeStep.output_contract, null, 2) : ""}
              disabled={isPublished}
              on:input={(e) => {
                try {
                  const val = e.currentTarget.value.trim() ? JSON.parse(e.currentTarget.value) : null;
                  updateStep("output_contract", val);
                } catch { /* ignore parse errors while typing */ }
              }}
              placeholder={'{"type": "object", "properties": {...}}'}
            ></textarea>
          </Settings.Row>

          {#if activeStep.input_source === "http_get" || activeStep.input_source === "http_post"}
            <Settings.Row title={m.flow_step_input_config()} description={m.flow_step_input_config_desc()}>
              <textarea
                class="border-default bg-primary ring-default min-h-[80px] w-full rounded-lg border px-3 py-2 font-mono text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                value={activeStep.input_config ? JSON.stringify(activeStep.input_config, null, 2) : ""}
                disabled={isPublished}
                on:input={(e) => {
                  try {
                    const val = e.currentTarget.value.trim() ? JSON.parse(e.currentTarget.value) : null;
                    updateStep("input_config", val);
                  } catch { /* ignore parse errors while typing */ }
                }}
                placeholder={'{"url": "https://...", "headers": {...}}'}
              ></textarea>
            </Settings.Row>
          {/if}

          {#if activeStep.output_mode === "http_post"}
            <Settings.Row title={m.flow_step_output_config()} description={m.flow_step_output_config_desc()}>
              <textarea
                class="border-default bg-primary ring-default min-h-[80px] w-full rounded-lg border px-3 py-2 font-mono text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                value={activeStep.output_config ? JSON.stringify(activeStep.output_config, null, 2) : ""}
                disabled={isPublished}
                on:input={(e) => {
                  try {
                    const val = e.currentTarget.value.trim() ? JSON.parse(e.currentTarget.value) : null;
                    updateStep("output_config", val);
                  } catch { /* ignore parse errors while typing */ }
                }}
                placeholder={'{"url": "https://...", "headers": {...}}'}
              ></textarea>
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
{/if}

<Dialog.Root alert bind:isOpen={showDeleteConfirm}>
  <Dialog.Content width="small">
    <Dialog.Title>{m.flow_step_remove()}</Dialog.Title>
    <Dialog.Description>{m.flow_step_remove_confirm()}</Dialog.Description>
    <Dialog.Controls let:close>
      <Button is={close}>{m.cancel()}</Button>
      <Button variant="destructive" on:click={() => {
        if (activeIndex >= 0) {
          dispatch("removeStep", activeIndex);
          $showDeleteConfirm = false;
        }
      }}>{m.delete()}</Button>
    </Dialog.Controls>
  </Dialog.Content>
</Dialog.Root>
