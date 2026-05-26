<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@intric/intric-js";
  import { slide } from "svelte/transition";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { IconChevronRight } from "@intric/icons/chevron-right";
  import { IconMicrophone } from "@intric/icons/microphone";
  import {
    getInputSourceOptionLabel,
    getInputTypeOptionLabel,
    getSourceHintText,
    getInputFormatHintText,
    getMimePresetsForFormat,
    parseMimeOverrideDraft
  } from "./flowStepEditHelpers";
  import {
    FILE_BASED_INPUT_TYPES,
    type FlowRuntimeInputConfigValue
  } from "$lib/features/flows/flowRuntimeInputConfig";
  import type { FlowSourceHintKind } from "$lib/features/flows/flowStepPresentation";
  import HttpConfigPanel from "./http/HttpConfigPanel.svelte";
  import { parseHttpAuthoredConfig, type HttpAuthoredConfig } from "./http/httpConfigTypes";
  import { createDefaultHttpConfig } from "./http/httpConfigDefaults";

  let {
    step,
    isPublished,
    selectableInputSourceOptions,
    displayedInputTypeOptions,
    runtimeInputConfig,
    sourceHintKind,
    sourceValidationMessage,
    inputSourceFeedback,
    inputTypeValidationMessage,
    inputTypeFeedback,
    transcriptionEnabled,
    transcriptionModelConfigured,
    transcriptionModelLabel,
    flowId = "",
    onInputSourceChange,
    onInputTypeChange,
    onRuntimeInputChange,
    onHttpConfigChange,
    onOpenTranscriptionSettings
  }: {
    step: FlowStep;
    isPublished: boolean;
    selectableInputSourceOptions: Array<{
      value: string;
      legacyInvalid: boolean;
    }>;
    displayedInputTypeOptions: Array<{
      value: string;
      disabled: boolean;
      legacyInvalid: boolean;
    }>;
    runtimeInputConfig: FlowRuntimeInputConfigValue;
    sourceHintKind: FlowSourceHintKind | null;
    sourceValidationMessage: string | null;
    inputSourceFeedback: string | null;
    inputTypeValidationMessage: string | null;
    inputTypeFeedback: string | null;
    transcriptionEnabled: boolean;
    transcriptionModelConfigured: boolean;
    transcriptionModelLabel: string | null;
    flowId?: string;
    onInputSourceChange?: (detail: { value: string }) => void;
    onInputTypeChange?: (detail: { value: string }) => void;
    onRuntimeInputChange?: (detail: { patch: Partial<FlowRuntimeInputConfigValue> }) => void;
    onHttpConfigChange?: (detail: { config: HttpAuthoredConfig }) => void;
    onOpenTranscriptionSettings?: () => void;
  } = $props();

  const isHttpSource = $derived(
    step.input_source === "http_get" || step.input_source === "http_post"
  );
  const httpMethod = $derived(
    step.input_source === "http_get" ? ("GET" as const) : ("POST" as const)
  );
  const defaultHttpConfig = $derived(createDefaultHttpConfig("input", httpMethod));
  const httpConfig = $derived(
    isHttpSource ? parseHttpAuthoredConfig(step.input_config, defaultHttpConfig) : defaultHttpConfig
  );

  let showRuntimeInputAdvanced = $state(false);

  function updateRuntimeInputSettings(patch: Partial<FlowRuntimeInputConfigValue>) {
    onRuntimeInputChange?.({ patch });
  }

  function toggleMimePreset(mime: string) {
    const current = runtimeInputConfig.accepted_mimetypes_override;
    const next = current.includes(mime) ? current.filter((m) => m !== mime) : [...current, mime];
    updateRuntimeInputSettings({ accepted_mimetypes_override: next });
  }
</script>

<Settings.Group title={m.flow_step_section_input()}>
  <Settings.Row
    title={m.flow_step_input_source_label()}
    description={m.flow_step_standard_input_desc()}
  >
    <div class="flex flex-col gap-2">
      <select
        class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
        value={step.input_source}
        disabled={isPublished}
        onchange={(e) => onInputSourceChange?.({ value: e.currentTarget.value })}
      >
        {#each selectableInputSourceOptions as source (source.value)}
          <option value={source.value}>
            {getInputSourceOptionLabel(source.value, source.legacyInvalid)}
          </option>
        {/each}
      </select>
      <p class="text-muted text-xs leading-relaxed" aria-live="polite">
        {getSourceHintText(sourceHintKind)}
      </p>
      {#if sourceValidationMessage || inputSourceFeedback}
        <p class="text-warning-stronger text-xs leading-relaxed" aria-live="polite">
          {sourceValidationMessage ?? inputSourceFeedback}
        </p>
      {/if}
    </div>
  </Settings.Row>

  <Settings.Row title={m.flow_step_input_type()} description={m.flow_step_input_format_desc()}>
    <div class="flex flex-col gap-2">
      <select
        class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
        value={step.input_type}
        disabled={isPublished}
        onchange={(e) => onInputTypeChange?.({ value: e.currentTarget.value })}
      >
        {#each displayedInputTypeOptions as option (option.value)}
          <option value={option.value} disabled={option.disabled}>
            {getInputTypeOptionLabel(option.value, option.legacyInvalid)}
          </option>
        {/each}
      </select>
      {#if getInputFormatHintText(sourceHintKind, step.input_type)}
        <p class="text-muted text-xs leading-relaxed" aria-live="polite">
          {getInputFormatHintText(sourceHintKind, step.input_type)}
        </p>
      {/if}
      {#if inputTypeValidationMessage || inputTypeFeedback}
        <p class="text-warning-stronger text-xs leading-relaxed" aria-live="polite">
          {inputTypeValidationMessage ?? inputTypeFeedback}
        </p>
      {/if}
    </div>
  </Settings.Row>

  <Settings.Row
    title={m.flow_runtime_input_title()}
    description={m.flow_runtime_input_description()}
    fullWidth={true}
  >
    <div class="flex flex-col gap-3">
      <label
        class="bg-primary flex items-start gap-3 rounded-lg border px-3 py-3 transition-colors {runtimeInputConfig.enabled
          ? 'border-accent-default/40'
          : 'border-default'}"
      >
        <input
          type="checkbox"
          class="accent-accent-default mt-0.5 size-4"
          checked={runtimeInputConfig.enabled}
          disabled={isPublished}
          aria-label={m.flow_runtime_input_accept_files()}
          onchange={(event) => updateRuntimeInputSettings({ enabled: event.currentTarget.checked })}
        />
        <div class="min-w-0">
          <p class="text-sm font-medium">{m.flow_runtime_input_accept_files()}</p>
          <p class="text-muted mt-1 text-xs leading-relaxed">
            {m.flow_runtime_input_accept_files_desc()}
          </p>
        </div>
      </label>

      {#if runtimeInputConfig.enabled}
        <div
          class="border-default/40 ml-1 flex flex-col gap-4 border-l pl-3 sm:ml-2 sm:pl-4"
          transition:slide={{ duration: 200 }}
        >
          <label class="flex items-start gap-3">
            <input
              type="checkbox"
              class="accent-accent-default mt-0.5 size-4"
              checked={runtimeInputConfig.required}
              disabled={isPublished}
              onchange={(event) =>
                updateRuntimeInputSettings({ required: event.currentTarget.checked })}
            />
            <div class="min-w-0">
              <p class="text-sm font-medium">{m.flow_runtime_input_required()}</p>
              <p class="text-muted mt-1 text-xs leading-relaxed">
                {m.flow_runtime_input_required_desc()}
              </p>
            </div>
          </label>

          <div class="flex flex-col gap-1">
            <label class="text-sm font-medium" for="runtime-input-format"
              >{m.flow_runtime_input_format_label()}</label
            >
            <select
              id="runtime-input-format"
              class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              value={runtimeInputConfig.input_format}
              disabled={isPublished ||
                step.output_mode === "transcribe_only" ||
                FILE_BASED_INPUT_TYPES.has(step.input_type)}
              onchange={(event) =>
                updateRuntimeInputSettings({
                  input_format: event.currentTarget
                    .value as FlowRuntimeInputConfigValue["input_format"]
                })}
            >
              <option value="document">{m.flow_runtime_input_format_document()}</option>
              <option value="audio">{m.flow_runtime_input_format_audio()}</option>
              <option value="file">{m.flow_runtime_input_format_file()}</option>
            </select>
          </div>

          <div class="flex flex-col gap-1">
            <label class="text-sm font-medium" for="runtime-input-description">
              {m.flow_runtime_input_instruction_label()}
            </label>
            <textarea
              id="runtime-input-description"
              class="border-default bg-primary ring-default min-h-[88px] w-full rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
              placeholder={m.flow_runtime_input_instruction_placeholder()}
              value={runtimeInputConfig.description}
              disabled={isPublished}
              oninput={(event) =>
                updateRuntimeInputSettings({ description: event.currentTarget.value })}
            ></textarea>
            <p class="text-muted text-xs leading-relaxed">
              {m.flow_runtime_input_instruction_hint()}
            </p>
          </div>

          <Collapsible.Root
            bind:open={showRuntimeInputAdvanced}
            class="border-default/70 bg-secondary/10 overflow-hidden rounded-lg border"
          >
            <Collapsible.Trigger
              class="hover:bg-secondary/20 flex w-full items-center gap-2 px-3 py-3 text-left text-sm font-medium transition-colors"
            >
              <IconChevronRight
                class="size-3.5 shrink-0 transition-transform duration-200 {showRuntimeInputAdvanced
                  ? 'rotate-90'
                  : ''}"
              />
              {m.flow_runtime_input_more_settings()}
            </Collapsible.Trigger>
            <Collapsible.Content>
              <div class="border-default/70 border-t px-3 pt-3 pb-3">
                <div class="grid gap-3 md:grid-cols-2">
                  <div class="flex flex-col gap-1">
                    <label class="text-sm font-medium" for="runtime-input-label"
                      >{m.flow_runtime_input_heading_label()}</label
                    >
                    <input
                      id="runtime-input-label"
                      class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                      type="text"
                      placeholder={m.flow_runtime_input_heading_placeholder()}
                      value={runtimeInputConfig.label}
                      disabled={isPublished}
                      oninput={(event) =>
                        updateRuntimeInputSettings({ label: event.currentTarget.value })}
                    />
                  </div>

                  <div class="flex flex-col gap-1">
                    <label class="text-sm font-medium" for="runtime-input-max-files">
                      {m.flow_input_limits_max_files_title()}
                    </label>
                    <input
                      id="runtime-input-max-files"
                      class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 text-sm shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                      type="number"
                      min="1"
                      inputmode="numeric"
                      placeholder={m.flow_runtime_input_max_files_placeholder()}
                      value={runtimeInputConfig.max_files ?? ""}
                      disabled={isPublished}
                      oninput={(event) =>
                        updateRuntimeInputSettings({
                          max_files:
                            event.currentTarget.value.trim().length > 0
                              ? Number(event.currentTarget.value)
                              : null
                        })}
                    />
                  </div>

                  <div class="flex flex-col gap-2 md:col-span-2">
                    <span class="text-sm font-medium">
                      {m.flow_runtime_input_mimetypes_label()}
                    </span>
                    <div class="flex flex-wrap gap-1.5">
                      {#each getMimePresetsForFormat(runtimeInputConfig.input_format) as preset (preset.mime)}
                        <button
                          type="button"
                          class="rounded-md border px-2.5 py-1 text-xs font-medium transition-colors {runtimeInputConfig.accepted_mimetypes_override.includes(
                            preset.mime
                          )
                            ? 'border-accent-default/60 bg-accent-dimmer/50 text-accent-stronger'
                            : 'border-default bg-primary text-secondary hover:bg-secondary/10'}"
                          disabled={isPublished}
                          onclick={() => toggleMimePreset(preset.mime)}
                        >
                          {preset.label}
                        </button>
                      {/each}
                    </div>
                    {#if runtimeInputConfig.accepted_mimetypes_override.some((mt) => !getMimePresetsForFormat(runtimeInputConfig.input_format).some((p) => p.mime === mt))}
                      <p class="text-muted text-xs">
                        + {runtimeInputConfig.accepted_mimetypes_override
                          .filter(
                            (mt) =>
                              !getMimePresetsForFormat(runtimeInputConfig.input_format).some(
                                (p) => p.mime === mt
                              )
                          )
                          .join(", ")}
                      </p>
                    {/if}
                    <input
                      id="runtime-input-mimetypes"
                      class="border-default bg-primary ring-default w-full rounded-lg border px-3 py-2 text-xs shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
                      type="text"
                      placeholder={m.flow_runtime_input_mimetypes_custom_placeholder()}
                      value={runtimeInputConfig.accepted_mimetypes_override
                        .filter(
                          (mt) =>
                            !getMimePresetsForFormat(runtimeInputConfig.input_format).some(
                              (p) => p.mime === mt
                            )
                        )
                        .join(", ")}
                      disabled={isPublished}
                      oninput={(event) => {
                        const presetMimes = runtimeInputConfig.accepted_mimetypes_override.filter(
                          (mt) =>
                            getMimePresetsForFormat(runtimeInputConfig.input_format).some(
                              (p) => p.mime === mt
                            )
                        );
                        const customMimes = parseMimeOverrideDraft(event.currentTarget.value);
                        updateRuntimeInputSettings({
                          accepted_mimetypes_override: [...presetMimes, ...customMimes]
                        });
                      }}
                    />
                    <p class="text-muted text-xs leading-relaxed">
                      {m.flow_runtime_input_mimetypes_hint()}
                    </p>
                  </div>
                </div>
              </div>
            </Collapsible.Content>
          </Collapsible.Root>
        </div>
      {/if}
    </div>
  </Settings.Row>
</Settings.Group>

{#if isHttpSource}
  <HttpConfigPanel
    config={httpConfig}
    direction="input"
    method={httpMethod}
    {isPublished}
    {flowId}
    onConfigChange={(detail) => onHttpConfigChange?.({ config: detail.config })}
  />
{/if}

{#if step.input_type === "audio"}
  <Alert.Root
    class="mb-3 flex items-center justify-between rounded-[1rem] px-5 py-4 {!transcriptionEnabled ||
    !transcriptionModelConfigured
      ? 'border-warning-default/30 bg-warning-dimmer/50'
      : 'border-accent-default/15 bg-accent-default/5'}"
    role="status"
  >
    <div class="flex items-center gap-2.5">
      <IconMicrophone
        class="size-4 shrink-0 {!transcriptionEnabled || !transcriptionModelConfigured
          ? 'text-warning-stronger/70'
          : 'text-accent-default'}"
      />
      <span
        class="text-[0.8125rem] font-medium {!transcriptionEnabled || !transcriptionModelConfigured
          ? 'text-warning-stronger'
          : 'text-primary'}"
      >
        {#if !transcriptionEnabled}
          {m.flow_transcription_audio_nudge()}
        {:else if !transcriptionModelConfigured}
          {m.flow_transcription_model_label()}:
          <span class="text-warning-stronger font-medium">{m.select_a_model()}</span>
        {:else}
          {m.flow_transcription_model_label()}:
          <span class="font-medium">{transcriptionModelLabel ?? "---"}</span>
        {/if}
      </span>
    </div>
    <button
      class="flex items-center gap-1 text-xs font-medium transition-colors {!transcriptionEnabled ||
      !transcriptionModelConfigured
        ? 'text-warning-stronger/80 hover:text-warning-stronger'
        : 'text-accent-default hover:text-accent-stronger'}"
      onclick={() => onOpenTranscriptionSettings?.()}
    >
      {m.edit()}
      {m.flow_stage_transcription()}
      <IconChevronRight class="size-3.5" />
    </button>
  </Alert.Root>
{/if}
