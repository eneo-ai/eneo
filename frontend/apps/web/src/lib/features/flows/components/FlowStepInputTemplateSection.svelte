<script lang="ts">
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@eneo/eneo-js";
  import { Button, buttonVariants } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
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
    inputTemplateSectionTitle,
    inputTemplateSectionDescription,
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
    inputTemplateSectionTitle: string;
    inputTemplateSectionDescription: string;
    onRevealInputTemplate?: () => void;
    onClearInputTemplate?: () => void;
    onInputTemplateChange?: (detail: { value: string }) => void;
    onInputSourcesChange?: (detail: { sourceRefs: FlowInputBindingSourceRef[] }) => void;
    onInputSourceChange?: (detail: { value: string }) => void;
  } = $props();

  const componentId = $props.id();
  const effectiveSourcesTitleId = `${componentId}-effective-sources-title`;
  const materialSearchId = `${componentId}-material-search`;

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
  const inputTemplateEditingAllowed = $derived(
    !isPublished &&
      !runtimeInputEnabled &&
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
  const shouldShowEffectiveInputSources = $derived(
    effectiveInputSources.length > 0 || sourceEditingNotice !== null
  );
  const shouldShowInputTemplateEditor = $derived(
    hasInputTemplateOverride || (showInputTemplate && inputTemplateEditingAllowed)
  );
  let materialPickerOpen = $state(false);
  let materialSearch = $state("");
  const availableMaterialGroups = $derived.by(() => {
    const query = materialSearch.trim().toLocaleLowerCase();
    const groups: Array<{
      stepOrder: number;
      stepName: string | null;
      options: FlowInputMaterialOption[];
    }> = [];
    for (const option of materialOptions) {
      if (selectedSourceRefs.some((ref) => sourceRefMatchesOption(ref, option))) continue;
      const searchText = [
        option.sourceStepName,
        option.fieldPath,
        option.description,
        option.fieldPath === null ? m.flow_input_material_whole_result() : null,
        option.output === "structured"
          ? m.flow_input_template_source_output_structured()
          : m.flow_input_template_source_output_text()
      ]
        .filter((value): value is string => value !== null)
        .join(" ")
        .toLocaleLowerCase();
      if (query && !searchText.includes(query)) continue;
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

  function setMaterialPickerOpen(open: boolean) {
    materialPickerOpen = open;
    if (!open) materialSearch = "";
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

{#if !isPowerUser && hasInputTemplateOverride}
  <Alert.Root
    class="border-warning-default/40 bg-warning-dimmer text-warning-stronger mb-3"
    role="status"
  >
    <Alert.Description class="text-warning-stronger flex items-start gap-3 text-xs">
      <span class="flex-1">{m.flow_input_template_active_notice()}</span>
      <div class="flex shrink-0 gap-1.5">
        {#if !showInputTemplate}
          <Button variant="outline" size="sm" onclick={() => onRevealInputTemplate?.()}>
            {m.show()}
          </Button>
        {/if}
        <Button
          variant="outline"
          size="sm"
          disabled={isPublished}
          onclick={() => onClearInputTemplate?.()}
        >
          {m.clear()}
        </Button>
      </div>
    </Alert.Description>
  </Alert.Root>
{/if}

{#if templateSourceConflict && isPowerUser}
  <Alert.Root class="border-warning-default/40 bg-warning-dimmer text-warning-stronger mb-3">
    <Alert.Description class="text-warning-stronger flex items-start gap-3 text-xs">
      <span class="flex-1">
        {m.flow_template_source_conflict_warning({
          steps: templateSourceConflict.map((n) => `Step ${n}`).join(", "),
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

{#if shouldShowEffectiveInputSources}
  <section class="mb-4 flex flex-col gap-3 px-2" aria-labelledby={effectiveSourcesTitleId}>
    <div class="flex items-center">
      <h3 id={effectiveSourcesTitleId} class="text-primary text-sm font-medium">
        {m.flow_input_template_effective_sources_title()}
      </h3>
      <Settings.InfoTip
        title={m.flow_input_template_effective_sources_title()}
        text={m.flow_input_material_help()}
      />
    </div>

    <div class="text-secondary flex flex-col gap-3 text-[0.8125rem] leading-relaxed">
      {#if effectiveInputSources.length > 0}
        <ul class="border-default divide-default flex flex-col divide-y rounded-lg border">
          {#each effectiveInputSources as source, index (`${source.kind}-${index}`)}
            {@const title = sourceTitle(source)}
            <li class="flex min-w-0 items-center gap-3 px-3 py-2.5">
              <div class="min-w-0 flex-1">
                <p class="text-primary truncate font-medium">{title}</p>
                <p class="text-muted mt-0.5 leading-snug">{sourceMeta(source)}</p>
              </div>
              {#if sourceEditingAllowed && (source.kind === "source_ref" || source.kind === "deleted_source")}
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

      {#if sourceEditingAllowed}
        <div class="flex flex-wrap items-center gap-2">
          {#if materialOptions.length > 0}
            <Popover.Root bind:open={materialPickerOpen} onOpenChange={setMaterialPickerOpen}>
              <Popover.Trigger>
                {#snippet child({ props })}
                  <button
                    {...props}
                    type="button"
                    class={buttonVariants({ variant: "outline", size: "sm" })}
                    aria-label={m.flow_input_material_change()}
                  >
                    <IconPlus data-icon="inline-start" aria-hidden="true" />
                    {m.flow_input_material_change()}
                  </button>
                {/snippet}
              </Popover.Trigger>
              <Popover.Content
                align="start"
                collisionPadding={16}
                class="max-h-(--bits-popover-content-available-height) w-(--bits-popover-anchor-width) min-w-80 overflow-hidden p-0"
              >
                <Popover.Header class="px-3 pt-3 pb-2">
                  <Popover.Title>{m.flow_input_material_change()}</Popover.Title>
                  <Popover.Description
                    >{m.flow_input_material_picker_description()}</Popover.Description
                  >
                </Popover.Header>
                <div class="border-default border-y px-3 py-2">
                  <label for={materialSearchId} class="sr-only">
                    {m.flow_input_material_picker_search()}
                  </label>
                  <Input
                    id={materialSearchId}
                    value={materialSearch}
                    placeholder={m.flow_input_material_picker_search()}
                    oninput={(event) => (materialSearch = event.currentTarget.value)}
                  />
                </div>
                <div class="min-h-0 flex-1 overflow-y-auto p-1.5">
                  {#if availableMaterialGroups.length === 0}
                    <p class="text-muted px-3 py-6 text-center text-sm">
                      {m.flow_input_material_no_options()}
                    </p>
                  {:else}
                    {#each availableMaterialGroups as group (group.stepOrder)}
                      <section aria-labelledby={`${componentId}-material-step-${group.stepOrder}`}>
                        <h4
                          id={`${componentId}-material-step-${group.stepOrder}`}
                          class="text-muted px-2 py-1.5 text-xs font-medium"
                        >
                          {stepLabel(group.stepOrder, group.stepName)}
                        </h4>
                        <ul>
                          {#each group.options as option (option.key)}
                            <li>
                              <button
                                type="button"
                                class="hover:bg-hover-dimmer focus-visible:ring-accent-default/30 flex w-full min-w-0 items-start rounded-md px-2 py-2 text-left focus-visible:ring-2 focus-visible:outline-none"
                                onclick={() => selectMaterial(option)}
                              >
                                <span class="min-w-0 flex-1">
                                  <span class="text-primary block truncate text-sm font-medium">
                                    {option.fieldPath ?? m.flow_input_material_whole_result()}
                                  </span>
                                  <span class="text-muted block truncate text-xs">
                                    {option.description ??
                                      (option.output === "structured"
                                        ? m.flow_input_template_source_output_structured()
                                        : m.flow_input_template_source_output_text())}
                                  </span>
                                </span>
                              </button>
                            </li>
                          {/each}
                        </ul>
                      </section>
                    {/each}
                  {/if}
                </div>
                <div class="border-default flex justify-end border-t px-3 py-2">
                  <Popover.Close>
                    {#snippet child({ props })}
                      <Button {...props} variant="ghost" size="sm">{m.done()}</Button>
                    {/snippet}
                  </Popover.Close>
                </div>
              </Popover.Content>
            </Popover.Root>
          {/if}

          {#if selectedSourceRefs.length > 0}
            <Button
              variant="ghost"
              size="sm"
              title={inputBindingsState.status === "valid" && inputBindingsState.question
                ? m.flow_input_material_clear_sources_description()
                : m.flow_input_material_default_description()}
              onclick={() => onInputSourcesChange?.({ sourceRefs: [] })}
            >
              {inputBindingsState.status === "valid" && inputBindingsState.question
                ? m.flow_input_material_clear_sources()
                : m.flow_input_material_default()}
            </Button>
          {/if}
        </div>
      {:else if sourceEditingNotice && !isPublished}
        <Alert.Root>
          <Alert.Description class="text-secondary text-xs leading-relaxed">
            {sourceEditingNotice}
          </Alert.Description>
        </Alert.Root>
      {/if}
    </div>
  </section>
{/if}

<FlowStepSection title={inputTemplateSectionTitle} {collapsible} {resetKey} status={templateStatus}>
  <div class="flex flex-col gap-3 px-2">
    <div class="flex max-w-3xl items-start gap-1">
      <p class="text-secondary text-[0.8125rem] leading-relaxed">
        {inputTemplateSectionDescription}
      </p>
      <Settings.InfoTip title={inputTemplateSectionTitle} text={m.flow_input_template_help()} />
    </div>
    {#if shouldShowInputTemplateEditor}
      <div class="flex flex-col gap-2">
        <p class="text-secondary text-[0.8125rem] leading-relaxed">
          {stepUxCopy.inputTemplateDefaultHint}
        </p>
        <FlowPromptEditor
          value={inputTemplateText}
          disabled={!inputTemplateEditingAllowed}
          label={stepUxCopy.inputTemplateEditorLabel}
          placeholder={stepUxCopy.inputTemplatePlaceholder}
          minHeight={isAdvancedMode ? 160 : 132}
          {steps}
          currentStepOrder={step.step_order}
          {formSchema}
          transcriptionEnabled={transcriptionEnabled && hasAudioInputSteps}
          {isAdvancedMode}
          onChange={(value) => onInputTemplateChange?.({ value })}
        />
      </div>
    {:else if inputTemplateEditingAllowed}
      <Button
        variant="outline"
        size="sm"
        class="self-start"
        onclick={() => onRevealInputTemplate?.()}
      >
        {stepUxCopy.inputTemplateCtaAction}
      </Button>
    {/if}
  </div>
</FlowStepSection>
