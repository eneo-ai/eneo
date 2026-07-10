<script lang="ts">
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { IconQuestionMark } from "@eneo/icons/question-mark";
  import { slide } from "svelte/transition";
  import FlowPromptEditor from "./FlowPromptEditor.svelte";
  import { INPUT_SOURCE_LABELS } from "./flowStepEditHelpers";
  import type { FlowFormSchemaMetadata } from "$lib/features/flows/flowFormSchema";
  import type { FlowStepEffectiveInputSource } from "$lib/features/flows/flowInputBindings";
  import type { FlowStepUxCopy } from "$lib/features/flows/flowStepUxCopy";

  let {
    step,
    isPublished,
    isAdvancedMode,
    isPowerUser,
    hasInputTemplateOverride,
    hasTypedInputSources,
    showInputTemplate,
    inputTemplateText,
    effectiveInputSources,
    templateSourceConflict,
    templateStepRefs,
    steps,
    formSchema,
    transcriptionEnabled,
    hasAudioInputSteps,
    stepUxCopy,
    inputTemplateSectionTitle,
    inputTemplateSectionDescription,
    onRevealInputTemplate,
    onClearInputTemplate,
    onInputTemplateChange,
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
    hasTypedInputSources: boolean;
    showInputTemplate: boolean;
    inputTemplateText: string;
    effectiveInputSources: FlowStepEffectiveInputSource[];
    templateSourceConflict: number[] | null;
    templateStepRefs: number[];
    steps: FlowStep[];
    formSchema: FlowFormSchemaMetadata | undefined;
    transcriptionEnabled: boolean;
    hasAudioInputSteps: boolean;
    stepUxCopy: FlowStepUxCopy;
    inputTemplateSectionTitle: string;
    inputTemplateSectionDescription: string;
    onRevealInputTemplate?: () => void;
    onClearInputTemplate?: () => void;
    onInputTemplateChange?: (detail: { value: string }) => void;
    onInputSourceChange?: (detail: { value: string }) => void;
  } = $props();

  const templateStatus = $derived(
    hasInputTemplateOverride
      ? m.flow_section_status_template_custom()
      : hasTypedInputSources
        ? m.flow_section_status_template_sources()
        : m.flow_section_status_template_standard()
  );

  const shouldShowEffectiveInputSources = $derived(
    effectiveInputSources.length > 0 &&
      (showInputTemplate || isAdvancedMode || hasTypedInputSources)
  );

  function stepLabel(stepOrder: number, stepName: string | null): string {
    const base = m.flow_input_template_effective_step({ step: stepOrder });
    return stepName ? `${base}: ${stepName}` : base;
  }

  function sourceTitle(source: FlowStepEffectiveInputSource): string {
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
      return source.stepRef;
    }
    return stepLabel(source.sourceStepOrder, source.sourceStepName);
  }

  function sourceMeta(source: FlowStepEffectiveInputSource): string {
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
      String(
        source.output === "structured"
          ? m.flow_input_template_source_output_structured()
          : m.flow_input_template_source_output_text()
      )
    ];
    if (source.fieldPath) {
      parts.push(source.fieldPath);
    }
    if (source.label) {
      parts.push(source.label);
    }
    return parts.join(" · ");
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
        <Button variant="outline" size="sm" onclick={() => onClearInputTemplate?.()}>
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
  <Alert.Root class="border-default bg-secondary/15 mb-3 rounded-lg" role="status">
    <Alert.Description class="text-secondary flex flex-col gap-2 text-xs leading-relaxed">
      <span class="text-primary font-medium">{m.flow_input_template_effective_sources_title()}</span
      >
      <ul class="flex flex-col gap-1.5">
        {#each effectiveInputSources as source, index (`${source.kind}-${index}`)}
          <li class="flex flex-wrap items-center gap-x-2 gap-y-1">
            <span class="text-primary font-medium">{sourceTitle(source)}</span>
            <span class="text-muted">{sourceMeta(source)}</span>
          </li>
        {/each}
      </ul>
    </Alert.Description>
  </Alert.Root>
{/if}

{#if showInputTemplate}
  <div transition:slide={{ duration: 200 }}>
    <FlowStepSection
      title={inputTemplateSectionTitle}
      {collapsible}
      {resetKey}
      status={templateStatus}
    >
      <Settings.Row title={inputTemplateSectionTitle} description={inputTemplateSectionDescription}>
        <svelte:fragment slot="title">
          <Tooltip.Provider delayDuration={150}>
            <Tooltip.Root>
              <Tooltip.Trigger aria-label={m.flow_step_input_template_tooltip()}>
                <IconQuestionMark class="text-muted hover:text-primary ml-1.5" aria-hidden="true" />
              </Tooltip.Trigger>
              <Tooltip.Content>{m.flow_step_input_template_tooltip()}</Tooltip.Content>
            </Tooltip.Root>
          </Tooltip.Provider>
        </svelte:fragment>
        <div class="flex flex-col gap-2">
          <Alert.Root class="bg-secondary/20 rounded-lg" role="status">
            <Alert.Description class="text-secondary text-xs leading-relaxed">
              {stepUxCopy.inputTemplateDefaultHint}
            </Alert.Description>
          </Alert.Root>
          <FlowPromptEditor
            value={inputTemplateText}
            disabled={isPublished}
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
      </Settings.Row>
    </FlowStepSection>
  </div>
{/if}
