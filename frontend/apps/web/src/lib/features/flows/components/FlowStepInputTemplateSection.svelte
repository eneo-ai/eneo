<svelte:options runes={false} />

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@intric/intric-js";
  import { createEventDispatcher } from "svelte";
  import { Button, Tooltip } from "@intric/ui";
  import { Alert } from "@eneo/ui";
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import { slide } from "svelte/transition";
  import FlowPromptEditor from "./FlowPromptEditor.svelte";
  import { INPUT_SOURCE_LABELS } from "./flowStepEditHelpers";

  export let step: FlowStep;
  export let isPublished: boolean;
  export let isAdvancedMode: boolean;
  export let isPowerUser: boolean;
  export let hasInputTemplateOverride: boolean;
  export let showInputTemplate: boolean;
  export let inputTemplateText: string;
  export let templateSourceConflict: number[] | null;
  export let templateStepRefs: number[];
  export let steps: FlowStep[];
  export let formSchema: any;
  export let transcriptionEnabled: boolean;
  export let hasAudioInputSteps: boolean;
  export let stepUxCopy: any;
  export let inputTemplateSectionTitle: string;
  export let inputTemplateSectionDescription: string;

  const dispatch = createEventDispatcher<{
    revealInputTemplate: void;
    clearInputTemplate: void;
    inputTemplateChange: { value: string };
    inputSourceChange: { value: string };
  }>();
</script>

{#if !isPowerUser && hasInputTemplateOverride}
  <Alert.Root class="mb-3 border-warning-default/40 bg-warning-dimmer text-warning-stronger" role="status">
    <Alert.Description class="flex items-start gap-3 text-xs text-warning-stronger">
      <span class="flex-1">{m.flow_input_template_active_notice()}</span>
      <div class="flex shrink-0 gap-1.5">
        {#if !showInputTemplate}
          <Button
            variant="outlined"
            size="small"
            on:click={() => dispatch("revealInputTemplate")}
          >
            {m.show()}
          </Button>
        {/if}
        <Button variant="outlined" size="small" on:click={() => dispatch("clearInputTemplate")}>
          {m.clear()}
        </Button>
      </div>
    </Alert.Description>
  </Alert.Root>
{/if}

{#if templateSourceConflict && isPowerUser}
  <Alert.Root class="mb-3 border-warning-default/40 bg-warning-dimmer text-warning-stronger">
    <Alert.Description class="flex items-start gap-3 text-xs text-warning-stronger">
      <span class="flex-1">
        {m.flow_template_source_conflict_warning({
          steps: templateSourceConflict.map((n) => `Step ${n}`).join(", "),
          source:
            INPUT_SOURCE_LABELS[step.input_source]?.() ?? step.input_source
        })}
      </span>
      <div class="flex shrink-0 gap-1.5">
        {#if step.input_source === "flow_input" && templateStepRefs.length === 1 && templateStepRefs[0] === step.step_order - 1}
          <Button
            variant="outlined"
            size="small"
            on:click={() => dispatch("inputSourceChange", { value: "previous_step" })}
            >{m.flow_template_source_conflict_fix_source()}</Button
          >
        {/if}
        <Button variant="outlined" size="small" on:click={() => dispatch("clearInputTemplate")}
          >{m.flow_template_source_conflict_fix_clear()}</Button
        >
      </div>
    </Alert.Description>
  </Alert.Root>
{/if}

{#if showInputTemplate}
  <div transition:slide={{ duration: 200 }}>
    <Settings.Group title={inputTemplateSectionTitle}>
      <Settings.Row
        title={inputTemplateSectionTitle}
        description={inputTemplateSectionDescription}
      >
        <svelte:fragment slot="title">
          <Tooltip text={m.flow_step_input_template_tooltip()}>
            <IconQuestionMark class="text-muted hover:text-primary ml-1.5" />
          </Tooltip>
        </svelte:fragment>
        <div class="flex flex-col gap-2">
          <Alert.Root class="border-l-[3px] border-l-stronger bg-secondary/20" role="status">
            <Alert.Description class="text-xs leading-relaxed text-secondary">
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
            on:change={(e) => dispatch("inputTemplateChange", { value: e.detail })}
          />
        </div>
      </Settings.Row>
    </Settings.Group>
  </div>
{/if}
