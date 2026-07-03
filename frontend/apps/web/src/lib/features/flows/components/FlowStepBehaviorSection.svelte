<script lang="ts">
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import type { CompletionModel, FlowStep, PromptSparse } from "@eneo/eneo-js";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import { CircleAlert } from "lucide-svelte";
  import { IconLoadingSpinner } from "@eneo/icons/loading-spinner";
  import { IconLockClosed } from "@eneo/icons/lock-closed";
  import { IconQuestionMark } from "@eneo/icons/question-mark";
  import SelectAIModelV2 from "$lib/features/ai-models/components/SelectAIModelV2.svelte";
  import SelectBehaviourV2 from "$lib/features/ai-models/components/SelectBehaviourV2.svelte";
  import SelectModelSpecificSettings from "$lib/features/ai-models/components/SelectModelSpecificSettings.svelte";
  import FlowPromptEditor from "./FlowPromptEditor.svelte";
  import type { FlowFormSchemaMetadata } from "$lib/features/flows/flowFormSchema";
  import type { LoadedAssistant } from "./FlowStepAssistantState.svelte";
  import type { FlowStepUxCopy } from "$lib/features/flows/flowStepUxCopy";
  import PromptVersionDialog from "$lib/features/prompts/components/PromptVersionDialog.svelte";
  import { supportsBehaviorPresets } from "$lib/features/ai-models/ModelKwargCapabilities.js";
  import { buildNextFlowPrompt } from "$lib/features/flows/flowPromptDraft";

  let {
    step,
    isPublished,
    isAdvancedMode,
    isTranscribeOnly,
    assistant,
    assistantLoading,
    availableModels,
    steps,
    formSchema,
    transcriptionEnabled,
    hasAudioInputSteps,
    stepUxCopy,
    instructionText,
    instructionMissing = false,
    focusInstruction = false,
    canRevealInputTemplate,
    showInputTemplate,
    loadPromptVersions,
    onAssistantFieldChange,
    onInstructionDraft,
    onInstructionCommit,
    onRevealInputTemplate,
    onInstructionFocused
  }: {
    step: FlowStep;
    isPublished: boolean;
    isAdvancedMode: boolean;
    isTranscribeOnly: boolean;
    assistant: LoadedAssistant | null;
    assistantLoading: boolean;
    availableModels: CompletionModel[];
    steps: FlowStep[];
    formSchema: FlowFormSchemaMetadata | undefined;
    transcriptionEnabled: boolean;
    hasAudioInputSteps: boolean;
    stepUxCopy: FlowStepUxCopy;
    instructionText: string;
    instructionMissing?: boolean;
    focusInstruction?: boolean;
    canRevealInputTemplate: boolean;
    showInputTemplate: boolean;
    loadPromptVersions: (assistantId: string) => Promise<PromptSparse[]>;
    onAssistantFieldChange?: (detail: { field: string; value: unknown }) => void;
    onInstructionDraft?: (detail: { value: string }) => void;
    onInstructionCommit?: (detail: { value: string }) => void;
    onRevealInputTemplate?: () => void;
    onInstructionFocused?: () => void;
  } = $props();

  // Onboarding comparison cards clutter the section once a step is configured.
  // Show them only while the instruction is empty, or on explicit "Visa tips".
  let showTips = $state(false);

  // Collapsed label for the advanced model group — the chosen model's name.
  const modelStatus = $derived(
    assistant?.completion_model?.nickname ?? assistant?.completion_model?.name ?? ""
  );

  function updateAssistantField(field: string, value: unknown) {
    onAssistantFieldChange?.({ field, value });
  }
</script>

<FlowStepSection>
  {#if step.output_mode === "transcribe_only"}
    <Alert.Root
      class="border-accent-default/15 bg-accent-default/5 mb-4 rounded-[1rem] px-5 py-4"
      role="status"
    >
      <IconLockClosed class="text-accent-default mt-0.5 size-4 shrink-0" />
      <Alert.Title class="text-accent-stronger text-sm font-semibold tracking-tight">
        {m.flow_transcribe_only_title()}
      </Alert.Title>
      <Alert.Description class="text-accent-stronger/80 flex flex-col gap-1.5">
        <span class="text-[0.8125rem] leading-relaxed">{m.flow_transcribe_only_description()}</span>
        <span class="text-accent-stronger/75 text-[0.8125rem] leading-relaxed"
          >{m.flow_transcribe_only_next_step_hint()}</span
        >
      </Alert.Description>
    </Alert.Root>
  {/if}
  {#if !isTranscribeOnly && assistantLoading}
    <div class="text-secondary flex items-center gap-2 px-4 py-3 text-sm">
      <IconLoadingSpinner class="size-4 animate-spin" />
      {m.flow_step_assistant_loading()}
    </div>
  {/if}

  {#if !isTranscribeOnly && assistant}
    {@const currentAssistant = assistant}
    <!-- The user's core task comes first: what should the AI do? Model and
         behaviour settings are secondary and live in a collapsed group below. -->
    <Settings.Row
      title={stepUxCopy.instructionsTitle}
      description={isAdvancedMode ? stepUxCopy.instructionsHelperTitle : ""}
      fullWidth
    >
      <svelte:fragment slot="title">
        <Tooltip.Provider delayDuration={150}>
          <Tooltip.Root>
            <Tooltip.Trigger>
              <IconQuestionMark class="text-muted hover:text-primary ml-1.5" />
            </Tooltip.Trigger>
            <Tooltip.Content>{m.flow_step_instructions_tooltip()}</Tooltip.Content>
          </Tooltip.Root>
        </Tooltip.Provider>
      </svelte:fragment>
      <div class="flex flex-col gap-2">
        {#if instructionMissing || showTips}
          <div class="grid gap-3 md:grid-cols-2">
            <Card.Root class="bg-hover-dimmer">
              <Card.Content class="px-3.5 py-3">
                <p class="text-accent-stronger text-sm font-semibold">
                  {m.flow_step_instructions_compare_title()}
                </p>
                <p class="text-secondary mt-1 text-xs leading-relaxed">
                  {m.flow_step_instructions_compare_body()}
                </p>
              </Card.Content>
            </Card.Root>
            <Card.Root class="bg-hover-dimmer">
              <Card.Content class="px-3.5 py-3">
                <p class="text-accent-stronger text-sm font-semibold">
                  {m.flow_step_input_template_compare_title()}
                </p>
                <p class="text-secondary mt-1 text-xs leading-relaxed">
                  {m.flow_step_input_template_compare_body()}
                </p>
              </Card.Content>
            </Card.Root>
          </div>
        {:else}
          <button
            type="button"
            class="text-accent-default hover:text-accent-stronger focus-visible:ring-accent-default/40 self-start rounded text-xs font-medium focus-visible:ring-2 focus-visible:outline-none"
            onclick={() => (showTips = true)}
          >
            {m.flow_step_instructions_show_tips()}
          </button>
        {/if}
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
                <Button variant="outline" size="sm" onclick={() => onRevealInputTemplate?.()}>
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
          focusOnMount={focusInstruction}
          invalid={instructionMissing}
          ariaDescribedby={instructionMissing ? "flow-step-instruction-missing" : undefined}
          placeholder={isAdvancedMode
            ? stepUxCopy.instructionsPlaceholder
            : stepUxCopy.instructionsPlaceholder}
          minHeight={isAdvancedMode ? 160 : 132}
          {steps}
          currentStepOrder={step.step_order}
          {formSchema}
          transcriptionEnabled={transcriptionEnabled && hasAudioInputSteps}
          {isAdvancedMode}
          onChange={(value) => onInstructionDraft?.({ value })}
          onCommit={(value) => onInstructionCommit?.({ value })}
          onFocused={onInstructionFocused}
        >
          {#snippet toolbar()}
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
          {/snippet}
        </FlowPromptEditor>
        {#if instructionMissing}
          <p
            id="flow-step-instruction-missing"
            class="text-warning-stronger flex items-center gap-1.5 text-xs leading-relaxed"
          >
            <CircleAlert class="size-3.5 shrink-0" aria-hidden="true" />
            {m.flow_step_instruction_missing()}
          </p>
        {/if}
      </div>
    </Settings.Row>

    {#if isAdvancedMode}
      <FlowStepSection
        title={m.flow_model_settings()}
        collapsible
        resetKey={step.step_order}
        status={modelStatus}
      >
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
            isDisabled={!supportsBehaviorPresets(currentAssistant.completion_model)}
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
      </FlowStepSection>
    {/if}
  {/if}
</FlowStepSection>
