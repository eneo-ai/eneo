<script lang="ts">
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@eneo/eneo-js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Command from "$lib/components/ui/command/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { IconPlus } from "@eneo/icons/plus";
  import { IconXMark } from "@eneo/icons/x-mark";
  import FlowPromptEditor from "./FlowPromptEditor.svelte";
  import { INPUT_SOURCE_LABELS } from "./flowStepEditHelpers";
  import type { FlowFormSchemaMetadata } from "$lib/features/flows/flowFormSchema";
  import {
    getFlowInputMaterialOptions,
    getFlowStepEffectiveInputSources,
    parseFlowInputBindings,
    type FlowInputBindingSourceRef,
    type FlowInputMaterialOption,
    type FlowStepEffectiveInputSource
  } from "$lib/features/flows/flowInputBindings";
  import type { FlowStepUxCopy } from "$lib/features/flows/flowStepUxCopy";

  let {
    step,
    isPublished,
    isAdvancedMode,
    isPowerUser,
    hasInputTemplateOverride,
    showInputTemplate,
    inputTemplateText,
    templateSourceConflict,
    templateStepRefs,
    steps,
    formSchema,
    transcriptionEnabled,
    hasAudioInputSteps,
    runtimeInputEnabled = false,
    stepUxCopy,
    onRevealInputTemplate,
    onClearInputTemplate,
    onInputTemplateChange,
    onInputSourcesChange,
    onInputSourceChange,
    collapsible = false,
    resetKey
  }: {
    collapsible?: boolean;
    resetKey?: string | number;
    step: FlowStep;
    isPublished: boolean;
    isAdvancedMode: boolean;
    isPowerUser: boolean;
    hasInputTemplateOverride: boolean;
    showInputTemplate: boolean;
    inputTemplateText: string;
    templateSourceConflict: number[] | null;
    templateStepRefs: number[];
    steps: FlowStep[];
    formSchema: FlowFormSchemaMetadata | undefined;
    transcriptionEnabled: boolean;
    hasAudioInputSteps: boolean;
    runtimeInputEnabled?: boolean;
    stepUxCopy: FlowStepUxCopy;
    onRevealInputTemplate?: () => void;
    onClearInputTemplate?: () => void;
    onInputTemplateChange?: (detail: { value: string }) => void;
    onInputSourcesChange?: (detail: { sourceRefs: FlowInputBindingSourceRef[] }) => void;
    onInputSourceChange?: (detail: { value: string }) => void;
  } = $props();

  const componentId = $props.id();
  const ownTextLabelId = `${componentId}-own-text-label`;

  const inputBindingsState = $derived(parseFlowInputBindings(step.input_bindings));
  const hasTypedInputSources = $derived(
    inputBindingsState.status === "valid" && inputBindingsState.sourceRefs.length > 0
  );
  const effectiveInputSources = $derived(getFlowStepEffectiveInputSources(step, steps));

  const templateStatus = $derived(
    hasInputTemplateOverride
      ? m.flow_section_status_template_custom()
      : hasTypedInputSources
        ? m.flow_section_status_template_sources()
        : m.flow_section_status_template_standard()
  );

  const materialOptions = $derived(getFlowInputMaterialOptions(step.step_order, steps));
  const selectedSourceRefs = $derived(
    inputBindingsState.status === "valid" ? inputBindingsState.sourceRefs : []
  );
  const sourceEditingAllowed = $derived(
    !isPublished &&
      !runtimeInputEnabled &&
      step.input_type === "text" &&
      step.input_contract == null &&
      inputBindingsState.status === "valid" &&
      !inputBindingsState.hasAdvancedSourceRefs
  );
  // A step that receives an upload keeps its custom text editable: the
  // runtime only requires that the text still includes the upload
  // (flow_validators._validate_runtime_input_publish_rules).
  const inputTemplateEditingAllowed = $derived(
    !isPublished &&
      step.input_type !== "json" &&
      step.input_contract == null &&
      inputBindingsState.status === "valid"
  );
  const sourceEditingNotice = $derived.by(() => {
    if (inputBindingsState.status === "invalid") return m.flow_input_material_invalid_notice();
    if (runtimeInputEnabled) return m.flow_input_material_runtime_locked_notice();
    if (step.input_type === "json" || step.input_contract != null) {
      return m.flow_input_material_json_locked_notice();
    }
    if (inputBindingsState.hasAdvancedSourceRefs) {
      if (step.output_mode !== "compose_text") {
        return m.flow_input_material_item_template_unsupported_notice();
      }
      return m.flow_input_material_advanced_notice();
    }
    if (step.input_type !== "text") {
      return m.flow_input_material_source_type_locked_notice();
    }
    return null;
  });
  const uploadLeftOut = $derived(
    runtimeInputEnabled &&
      inputTemplateText.trim().length > 0 &&
      !/\{\{\s*step_input\./.test(inputTemplateText)
  );
  const shouldShowInputTemplateEditor = $derived(
    hasInputTemplateOverride || (showInputTemplate && inputTemplateEditingAllowed)
  );
  let materialPickerOpen = $state(false);
  // Results from earlier steps not chosen yet, grouped by step; Command
  // filters them as the person types.
  const availableMaterialGroups = $derived.by(() => {
    const groups: Array<{
      stepOrder: number;
      stepName: string | null;
      options: FlowInputMaterialOption[];
    }> = [];
    for (const option of materialOptions) {
      if (selectedSourceRefs.some((ref) => sourceRefMatchesOption(ref, option))) continue;
      const existing = groups.find((group) => group.stepOrder === option.sourceStepOrder);
      if (existing) {
        existing.options.push(option);
      } else {
        groups.push({
          stepOrder: option.sourceStepOrder,
          stepName: option.sourceStepName,
          options: [option]
        });
      }
    }
    return groups;
  });

  // What the step reads when it has no text of its own: the one sentence
  // that answers "what does the AI get here" (runtime order:
  // input_bindings.question, then chosen results, then the step's source).
  const defaultMaterial = $derived.by((): string | null => {
    if (selectedSourceRefs.length > 0) return m.flow_material_what_sources();
    if (runtimeInputEnabled) return m.flow_material_what_upload();
    if (step.input_source === "previous_step" && step.step_order > 1) {
      const previous = steps.find((candidate) => candidate.step_order === step.step_order - 1);
      if (previous) {
        return m.flow_material_what_previous({
          step: stepLabel(previous.step_order, previous.user_description ?? null)
        });
      }
    }
    if (step.input_source === "all_previous_steps" && step.step_order > 1) {
      return m.flow_material_what_all_previous();
    }
    if (step.input_source === "http_get") return m.flow_material_what_http();
    if (step.input_source === "flow_input") return m.flow_material_what_flow_input();
    return null;
  });
  const ownTextIncludesUpload = $derived(/\{\{\s*step_input\./.test(inputTemplateText));
  const currentMaterial = $derived.by((): string | null => {
    if (!hasInputTemplateOverride) return defaultMaterial;
    if (selectedSourceRefs.length > 0) return m.flow_material_what_own_text_and_sources();
    if (runtimeInputEnabled && ownTextIncludesUpload) {
      return m.flow_material_what_own_text_with_upload();
    }
    return m.flow_material_what_own_text();
  });
  const chosenSources = $derived(
    effectiveInputSources.filter(
      (source) => source.kind === "source_ref" || source.kind === "deleted_source"
    )
  );
  // Locks worth explaining. An upload step needs no note: the sentence above
  // already says the step reads the upload.
  const materialNotice = $derived(runtimeInputEnabled ? null : sourceEditingNotice);

  function stepLabel(stepOrder: number, stepName: string | null): string {
    const base = m.flow_input_template_effective_step({ step: stepOrder });
    return stepName ? `${base}: ${stepName}` : base;
  }

  function sourceTitle(source: FlowStepEffectiveInputSource): string {
    if (source.kind === "custom_question") {
      return m.flow_input_material_custom_text();
    }
    if (source.kind === "implicit_previous_step") {
      return stepLabel(source.sourceStepOrder, source.sourceStepName);
    }
    if (source.kind === "implicit_all_previous_steps") {
      return source.sourceSteps.map((item) => stepLabel(item.stepOrder, item.stepName)).join(", ");
    }
    if (source.kind === "deleted_source") {
      return stepLabel(source.deletedStepOrder, null);
    }
    if (source.sourceStepOrder === null) {
      return m.flow_input_material_unknown_source();
    }
    return stepLabel(source.sourceStepOrder, source.sourceStepName);
  }

  function sourceMeta(source: FlowStepEffectiveInputSource): string {
    if (source.kind === "custom_question") {
      return m.flow_input_material_custom_text_description();
    }
    if (source.kind === "implicit_previous_step") {
      return m.flow_input_template_effective_previous_step();
    }
    if (source.kind === "implicit_all_previous_steps") {
      return m.flow_input_template_effective_all_previous_steps();
    }
    if (source.kind === "deleted_source") {
      return String(m.flow_input_template_deleted_source_ref());
    }

    const parts: string[] = [
      source.output === "structured"
        ? m.flow_input_template_source_output_structured()
        : m.flow_input_template_source_output_text()
    ];
    if (source.fieldPath) {
      parts.push(m.flow_input_material_selected_field({ field: source.fieldPath }));
    } else {
      parts.push(m.flow_input_material_whole_result());
    }
    if (source.label) {
      parts.push(source.label);
    }
    return parts.join(" · ");
  }

  function sourceRefMatchesOption(
    sourceRef: FlowInputBindingSourceRef,
    option: FlowInputMaterialOption
  ): boolean {
    return (
      sourceRef.stepRef === option.stepRef &&
      sourceRef.output === option.output &&
      sourceRef.fieldPath === option.fieldPath &&
      sourceRef.itemTemplate === null
    );
  }

  function selectMaterial(option: FlowInputMaterialOption) {
    onInputSourcesChange?.({
      sourceRefs: [
        ...selectedSourceRefs,
        {
          stepRef: option.stepRef,
          output: option.output,
          fieldPath: option.fieldPath,
          label: null,
          itemTemplate: null
        }
      ]
    });
  }

  function removeMaterial(source: FlowStepEffectiveInputSource) {
    if (source.kind !== "source_ref" && source.kind !== "deleted_source") return;
    const index = selectedSourceRefs.findIndex(
      (ref) =>
        ref.stepRef === source.stepRef &&
        ref.output === source.output &&
        ref.fieldPath === source.fieldPath &&
        ref.label === source.label &&
        ref.itemTemplate === source.itemTemplate
    );
    if (index === -1) return;
    onInputSourcesChange?.({
      sourceRefs: selectedSourceRefs.filter((_, sourceIndex) => sourceIndex !== index)
    });
  }
</script>

<FlowStepSection title={m.flow_material_title()} {collapsible} {resetKey} status={templateStatus}>
  <div class="flex max-w-3xl flex-col gap-4 px-2">
    {#if currentMaterial}
      <!-- The one answer this block owes: what the AI gets in this step. -->
      <div class="flex items-start gap-1">
        <p class="text-primary text-sm leading-relaxed" aria-live="polite">
          {m.flow_material_reads({ what: currentMaterial })}
        </p>
        <Settings.InfoTip title={m.flow_material_title()} text={m.flow_material_help()} />
      </div>
    {/if}

    {#if templateSourceConflict && isPowerUser}
      <Alert.Root class="border-warning-default/40 bg-warning-dimmer text-warning-stronger mb-3">
        <Alert.Description class="text-warning-stronger flex items-start gap-3 text-xs">
          <span class="flex-1">
            {m.flow_template_source_conflict_warning({
              steps: templateSourceConflict
                .map((n) => m.flow_step_fallback_label({ order: n }))
                .join(", "),
              source: INPUT_SOURCE_LABELS[step.input_source]?.() ?? step.input_source
            })}
          </span>
          <div class="flex shrink-0 gap-1.5">
            {#if step.input_source === "flow_input" && templateStepRefs.length === 1 && templateStepRefs[0] === step.step_order - 1}
              <Button
                variant="outline"
                size="sm"
                onclick={() => onInputSourceChange?.({ value: "previous_step" })}
                >{m.flow_template_source_conflict_fix_source()}</Button
              >
            {/if}
            <Button variant="outline" size="sm" onclick={() => onClearInputTemplate?.()}
              >{m.flow_template_source_conflict_fix_clear()}</Button
            >
          </div>
        </Alert.Description>
      </Alert.Root>
    {/if}

    {#if chosenSources.length > 0 || sourceEditingAllowed}
      <div class="flex flex-col gap-2">
        {#if chosenSources.length > 0}
          <ul class="border-default divide-default flex flex-col divide-y rounded-lg border">
            {#each chosenSources as source, index (`${source.kind}-${index}`)}
              {@const title = sourceTitle(source)}
              <li class="flex min-w-0 items-center gap-3 px-3 py-2">
                <div class="min-w-0 flex-1">
                  <p class="text-primary truncate text-sm font-medium">{title}</p>
                  <p class="text-secondary text-xs leading-snug">{sourceMeta(source)}</p>
                </div>
                {#if sourceEditingAllowed}
                  <Button
                    variant="ghost"
                    size="icon-sm"
                    aria-label={m.flow_input_material_remove({ source: title })}
                    onclick={() => removeMaterial(source)}
                  >
                    <IconXMark aria-hidden="true" />
                  </Button>
                {/if}
              </li>
            {/each}
          </ul>
        {/if}
        {#if sourceEditingAllowed && materialOptions.length > 0}
          <div class="flex flex-wrap items-center gap-2">
            <Popover.Root bind:open={materialPickerOpen}>
              <Popover.Trigger>
                {#snippet child({ props })}
                  <button
                    {...props}
                    type="button"
                    class={buttonVariants({ variant: "outline", size: "sm" })}
                  >
                    <IconPlus data-icon="inline-start" aria-hidden="true" />
                    {m.flow_input_material_change()}
                  </button>
                {/snippet}
              </Popover.Trigger>
              <Popover.Content
                align="start"
                collisionPadding={16}
                class="w-[min(28rem,calc(100vw-2rem))] p-0"
              >
                <Command.Root>
                  <Command.Input placeholder={m.flow_input_material_picker_search()} />
                  <Command.List class="max-h-[min(22rem,60vh)]">
                    <Command.Empty>{m.flow_input_material_no_options()}</Command.Empty>
                    {#each availableMaterialGroups as group (group.stepOrder)}
                      <Command.Group heading={stepLabel(group.stepOrder, group.stepName)}>
                        {#each group.options as option (option.key)}
                          <Command.Item
                            value={option.key}
                            keywords={[
                              stepLabel(group.stepOrder, group.stepName),
                              option.fieldPath ?? m.flow_input_material_whole_result(),
                              option.description ?? ""
                            ]}
                            onSelect={() => {
                              selectMaterial(option);
                              materialPickerOpen = false;
                            }}
                            class="items-start py-2"
                          >
                            <span class="flex min-w-0 flex-col gap-0.5">
                              <span class="text-primary truncate text-sm font-medium">
                                {option.fieldPath ?? m.flow_input_material_whole_result()}
                              </span>
                              <span class="text-secondary truncate text-xs">
                                {option.description ??
                                  (option.output === "structured"
                                    ? m.flow_input_template_source_output_structured()
                                    : m.flow_input_template_source_output_text())}
                              </span>
                            </span>
                          </Command.Item>
                        {/each}
                      </Command.Group>
                    {/each}
                  </Command.List>
                </Command.Root>
              </Popover.Content>
            </Popover.Root>
            {#if selectedSourceRefs.length > 0}
              <Button
                variant="ghost"
                size="sm"
                onclick={() => onInputSourcesChange?.({ sourceRefs: [] })}
              >
                {inputBindingsState.status === "valid" && inputBindingsState.question
                  ? m.flow_input_material_clear_sources()
                  : m.flow_input_material_default()}
              </Button>
            {/if}
          </div>
        {/if}
      </div>
    {/if}

    {#if materialNotice && !isPublished}
      <p class="text-secondary text-xs leading-relaxed">{materialNotice}</p>
    {/if}

    {#if shouldShowInputTemplateEditor}
      <section class="flex flex-col gap-2" aria-labelledby={ownTextLabelId}>
        <div class="flex min-h-8 items-center justify-between gap-2">
          <div class="flex items-center gap-1">
            <h3 id={ownTextLabelId} class="text-primary text-sm font-medium">
              {m.flow_material_own_text()}
            </h3>
            <Settings.InfoTip
              title={m.flow_material_own_text()}
              text={m.flow_input_template_help()}
            />
          </div>
          {#if hasInputTemplateOverride && !isPublished}
            <Button variant="ghost" size="sm" onclick={() => onClearInputTemplate?.()}>
              {m.flow_material_own_text_remove()}
            </Button>
          {/if}
        </div>
        <FlowPromptEditor
          value={inputTemplateText}
          disabled={!inputTemplateEditingAllowed}
          label={m.flow_material_own_text()}
          placeholder={stepUxCopy.inputTemplatePlaceholder}
          minHeight={isAdvancedMode ? 160 : 132}
          {steps}
          currentStepOrder={step.step_order}
          {formSchema}
          transcriptionEnabled={transcriptionEnabled && hasAudioInputSteps}
          uploadVariableAvailable={runtimeInputEnabled}
          {isAdvancedMode}
          onChange={(value) => onInputTemplateChange?.({ value })}
        />
        {#if uploadLeftOut}
          <Alert.Root class="border-warning-default/30 bg-warning-dimmer rounded-[9px]" role="note">
            <Alert.Description class="text-warning-stronger text-xs leading-relaxed">
              {m.flow_input_template_upload_left_out()}
            </Alert.Description>
          </Alert.Root>
        {:else if inputTemplateEditingAllowed && defaultMaterial}
          <p class="text-secondary text-xs leading-relaxed">
            {runtimeInputEnabled
              ? m.flow_material_own_text_help_upload({ fallback: defaultMaterial })
              : m.flow_material_own_text_help({ fallback: defaultMaterial })}
          </p>
        {/if}
      </section>
    {:else if inputTemplateEditingAllowed}
      <Button
        variant="outline"
        size="sm"
        class="self-start"
        onclick={() => onRevealInputTemplate?.()}
      >
        {m.flow_material_own_text_add()}
      </Button>
    {/if}
  </div>
</FlowStepSection>
