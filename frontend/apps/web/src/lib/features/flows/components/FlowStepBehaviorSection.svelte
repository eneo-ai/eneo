<svelte:options runes={false} />

<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { createEventDispatcher } from "svelte";
  import { Button, Tooltip } from "@intric/ui";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { IconLockClosed } from "@intric/icons/lock-closed";
  import { IconQuestionMark } from "@intric/icons/question-mark";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectBehaviourV2 from "$lib/features/ai-models/components/SelectBehaviourV2.svelte";
  import SelectModelSpecificSettings from "$lib/features/ai-models/components/SelectModelSpecificSettings.svelte";
  import FlowPromptEditor from "./FlowPromptEditor.svelte";
  import PromptVersionDialog from "$lib/features/prompts/components/PromptVersionDialog.svelte";
  import { supportsTemperature } from "$lib/features/ai-models/supportsTemperature.js";
  import { buildNextFlowPrompt } from "$lib/features/flows/flowPromptDraft";

  export let step: FlowStep;
  export let isPublished: boolean;
  export let isAdvancedMode: boolean;
  export let isTranscribeOnly: boolean;
  export let assistant: any | null;
  export let assistantLoading: boolean;
  export let availableModels: any[];
  export let steps: FlowStep[];
  export let formSchema: any;
  export let transcriptionEnabled: boolean;
  export let hasAudioInputSteps: boolean;
  export let stepUxCopy: any;
  export let instructionText: string;
  export let canRevealInputTemplate: boolean;
  export let showInputTemplate: boolean;
  export let loadPromptVersions: (assistantId: string) => Promise<any[]>;

  const dispatch = createEventDispatcher<{
    assistantFieldChange: { field: string; value: unknown };
    instructionDraft: { value: string };
    instructionCommit: { value: string };
    revealInputTemplate: void;
  }>();

  function updateAssistantField(field: string, value: unknown) {
    dispatch("assistantFieldChange", { field, value });
  }
</script>

<Settings.Group title={m.flow_step_section_behavior()}>
  {#if step.output_mode === "transcribe_only"}
    <div
      class="border-accent-default/15 bg-accent-default/5 mb-4 flex items-start gap-3 rounded-[1rem] border px-5 py-4"
    >
      <IconLockClosed class="text-accent-default mt-0.5 size-4 shrink-0" />
      <div class="flex flex-col gap-1.5">
        <span class="text-accent-stronger text-sm font-semibold tracking-tight"
          >{m.flow_transcribe_only_title()}</span
        >
        <span class="text-accent-stronger/80 text-[0.8125rem] leading-relaxed"
          >{m.flow_transcribe_only_description()}</span
        >
        <span class="text-accent-stronger/75 text-[0.8125rem] leading-relaxed"
          >{m.flow_transcribe_only_next_step_hint()}</span
        >
      </div>
    </div>
  {/if}
  {#if !isTranscribeOnly && assistantLoading}
    <div class="text-secondary flex items-center gap-2 px-4 py-3 text-sm">
      <IconLoadingSpinner class="size-4 animate-spin" />
      {m.flow_step_assistant_loading()}
    </div>
  {/if}

  {#if !isTranscribeOnly && assistant}
    {@const currentAssistant = assistant}
    <div class="w-full [&>button]:w-full">
      <SelectAIModelV2
        bind:selectedModel={currentAssistant.completion_model}
        {availableModels}
        on:change={() =>
          updateAssistantField("completion_model", currentAssistant.completion_model)}
      />
    </div>

    <Settings.Row title={m.model_behaviour()} description="">
      <SelectBehaviourV2
        bind:kwArgs={currentAssistant.completion_model_kwargs}
        selectedModel={currentAssistant.completion_model}
        isDisabled={!supportsTemperature(currentAssistant.completion_model?.name)}
        on:change={() =>
          updateAssistantField(
            "completion_model_kwargs",
            currentAssistant.completion_model_kwargs
          )}
      />
      <SelectModelSpecificSettings
        bind:kwArgs={currentAssistant.completion_model_kwargs}
        selectedModel={currentAssistant.completion_model}
        on:change={() =>
          updateAssistantField(
            "completion_model_kwargs",
            currentAssistant.completion_model_kwargs
          )}
      />
    </Settings.Row>

    <Settings.Row
      title={stepUxCopy.instructionsTitle}
      description={isAdvancedMode ? stepUxCopy.instructionsHelperTitle : ""}
      fullWidth
    >
      <svelte:fragment slot="title">
        <Tooltip text={m.flow_step_instructions_tooltip()}>
          <IconQuestionMark class="text-muted hover:text-primary ml-1.5" />
        </Tooltip>
      </svelte:fragment>
      <div class="flex flex-col gap-2">
        <div class="grid gap-3 md:grid-cols-2">
          <div class="border-default bg-hover-dimmer rounded-lg border px-3.5 py-3">
            <p class="text-accent-stronger text-sm font-semibold">
              {m.flow_step_instructions_compare_title()}
            </p>
            <p class="text-secondary mt-1 text-xs leading-relaxed">
              {m.flow_step_instructions_compare_body()}
            </p>
          </div>
          <div class="border-default bg-hover-dimmer rounded-lg border px-3.5 py-3">
            <p class="text-accent-stronger text-sm font-semibold">
              {m.flow_step_input_template_compare_title()}
            </p>
            <p class="text-secondary mt-1 text-xs leading-relaxed">
              {m.flow_step_input_template_compare_body()}
            </p>
          </div>
        </div>
        {#if !isAdvancedMode}
          <div class="flex flex-col gap-3 px-0.5 pt-0.5 pb-1.5">
            <div class="max-w-2xl min-w-0">
              <p class="text-primary text-sm font-medium">
                {stepUxCopy.instructionsHelperTitle}
              </p>
              <p class="text-muted mt-1 text-xs leading-relaxed">
                {stepUxCopy.instructionsHelperBody}
              </p>
            </div>
            {#if canRevealInputTemplate && !showInputTemplate}
              <div
                class="border-default bg-secondary/15 flex flex-wrap items-start justify-between gap-3 rounded-xl border px-3 py-3"
              >
                <div class="max-w-2xl min-w-0">
                  <p class="text-primary text-sm font-medium">
                    {stepUxCopy.inputTemplateCtaTitle}
                  </p>
                  <p class="text-muted mt-1 text-xs leading-relaxed">
                    {stepUxCopy.inputTemplateDefaultHint}
                  </p>
                </div>
                <Button
                  variant="outlined"
                  size="small"
                  on:click={() => dispatch("revealInputTemplate")}
                >
                  {stepUxCopy.inputTemplateCtaAction}
                </Button>
              </div>
            {/if}
          </div>
        {/if}
        <FlowPromptEditor
          value={instructionText}
          disabled={isPublished || assistantLoading || !assistant}
          label={stepUxCopy.instructionsTitle}
          placeholder={isAdvancedMode
            ? stepUxCopy.instructionsPlaceholder
            : stepUxCopy.instructionsPlaceholder}
          minHeight={isAdvancedMode ? 160 : 132}
          {steps}
          currentStepOrder={step.step_order}
          {formSchema}
          transcriptionEnabled={transcriptionEnabled && hasAudioInputSteps}
          {isAdvancedMode}
          on:change={(e) => dispatch("instructionDraft", { value: e.detail })}
          on:commit={(e) => dispatch("instructionCommit", { value: e.detail })}
        >
          <svelte:fragment slot="toolbar">
            {#if assistant?.id && !isPublished}
              <PromptVersionDialog
                title={m.prompt_history_for({ name: m.instructions() })}
                loadPromptVersionHistory={() => {
                  return loadPromptVersions(step.assistant_id);
                }}
                onPromptSelected={(prompt) => {
                  if (assistant?.prompt) {
                    updateAssistantField("prompt", {
                      ...buildNextFlowPrompt(assistant.prompt, prompt.text)
                    });
                  }
                }}
              />
            {/if}
          </svelte:fragment>
        </FlowPromptEditor>
      </div>
    </Settings.Row>
  {/if}
</Settings.Group>
