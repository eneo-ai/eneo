<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@intric/intric-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { slide } from "svelte/transition";
  import FlowPromptEditor from "./FlowPromptEditor.svelte";
  import { INPUT_SOURCE_LABELS } from "./flowStepEditHelpers";
  import type { FlowFormSchemaMetadata } from "$lib/features/flows/flowFormSchema";
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
    stepUxCopy,
    inputTemplateSectionTitle,
    inputTemplateSectionDescription,
    onRevealInputTemplate,
    onClearInputTemplate,
    onInputTemplateChange,
    onInputSourceChange
  }: {
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
    stepUxCopy: FlowStepUxCopy;
    inputTemplateSectionTitle: string;
    inputTemplateSectionDescription: string;
    onRevealInputTemplate?: () => void;
    onClearInputTemplate?: () => void;
    onInputTemplateChange?: (detail: { value: string }) => void;
    onInputSourceChange?: (detail: { value: string }) => void;
  } = $props();
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

{#if showInputTemplate}
  <div transition:slide={{ duration: 200 }}>
    <Settings.Group title={inputTemplateSectionTitle}>
      <Settings.Row title={inputTemplateSectionTitle} description={inputTemplateSectionDescription}>
        <svelte:fragment slot="title">
          <Tooltip.Provider delayDuration={150}>
            <Tooltip.Root>
              <Tooltip.Trigger>
                <IconQuestionMark class="text-muted hover:text-primary ml-1.5" />
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
    </Settings.Group>
  </div>
{/if}
