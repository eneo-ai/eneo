<svelte:options runes={false} />

<script lang="ts">
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@intric/intric-js";
  import { createEventDispatcher } from "svelte";
  import { slide } from "svelte/transition";
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
  import type { HttpAuthoredConfig } from "./http/httpConfigTypes";
  import { createDefaultHttpConfig } from "./http/httpConfigDefaults";

  export let step: FlowStep;
  export let isPublished: boolean;
  export let selectableInputSourceOptions: Array<{
    value: string;
    legacyInvalid: boolean;
  }>;
  export let displayedInputTypeOptions: Array<{
    value: string;
    disabled: boolean;
    legacyInvalid: boolean;
  }>;
  export let runtimeInputConfig: FlowRuntimeInputConfigValue;
  export let sourceHintKind: FlowSourceHintKind | null;
  export let sourceValidationMessage: string | null;
  export let inputSourceFeedback: string | null;
  export let inputTypeValidationMessage: string | null;
  export let inputTypeFeedback: string | null;
  export let transcriptionEnabled: boolean;
  export let transcriptionModelConfigured: boolean;
  export let transcriptionModelLabel: string | null;
  export let flowId: string = "";

  const dispatch = createEventDispatcher<{
    inputSourceChange: { value: string };
    inputTypeChange: { value: string };
    runtimeInputChange: { patch: Partial<FlowRuntimeInputConfigValue> };
    httpConfigChange: { config: HttpAuthoredConfig };
    openTranscriptionSettings: void;
  }>();

  $: isHttpSource = step.input_source === "http_get" || step.input_source === "http_post";
  $: httpMethod = step.input_source === "http_get" ? "GET" as const : "POST" as const;
  $: httpConfig = isHttpSource && step.input_config?.auth
    ? (step.input_config as unknown as HttpAuthoredConfig)
    : createDefaultHttpConfig("input", httpMethod);

  let showRuntimeInputAdvanced = false;

  function handleInputSourceChange(value: string) {
    dispatch("inputSourceChange", { value });
  }

  function handleInputTypeChange(value: string) {
    dispatch("inputTypeChange", { value });
  }

  function updateRuntimeInputSettings(patch: Partial<FlowRuntimeInputConfigValue>) {
    dispatch("runtimeInputChange", { patch });
  }

  function toggleMimePreset(mime: string) {
    const current = runtimeInputConfig.accepted_mimetypes_override;
    const next = current.includes(mime)
      ? current.filter((m) => m !== mime)
      : [...current, mime];
    updateRuntimeInputSettings({ accepted_mimetypes_override: next });
  }
</script>

<Settings.Group title={m.flow_step_section_input()}>
  <Settings.Row
    title={m.flow_step_input_source_label()}
    description={m.flow_step_standard_input_desc()}
    let:aria
  >
    <div class="flex flex-col gap-2">
      <select
        class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
        value={step.input_source}
        disabled={isPublished}
        on:change={(e) =>
          handleInputSourceChange(e.currentTarget.value)}
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

  <Settings.Row
    title={m.flow_step_input_type()}
    description={m.flow_step_input_format_desc()}
    let:aria
  >
    <div class="flex flex-col gap-2">
      <select
        class="border-default bg-primary w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:border-accent-default focus-within:ring-2 focus-within:ring-accent-default/20 hover:border-stronger focus-visible:outline-none disabled:opacity-50"
        value={step.input_type}
        disabled={isPublished}
        on:change={(e) =>
          handleInputTypeChange(e.currentTarget.value)}
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
          on:change={(event) =>
            updateRuntimeInputSettings({ enabled: event.currentTarget.checked })}
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
          class="border-default/40 ml-1 flex flex-col gap-4 border-l-2 pl-3 sm:ml-2 sm:pl-4"
          transition:slide={{ duration: 200 }}
        >
          <label class="flex items-start gap-3">
            <input
              type="checkbox"
              class="accent-accent-default mt-0.5 size-4"
              checked={runtimeInputConfig.required}
              disabled={isPublished}
              on:change={(event) =>
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
              on:change={(event) =>
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
              on:input={(event) =>
                updateRuntimeInputSettings({ description: event.currentTarget.value })}
            ></textarea>
            <p class="text-muted text-xs leading-relaxed">
              {m.flow_runtime_input_instruction_hint()}
            </p>
          </div>

          <div
            class="border-default/70 bg-secondary/10 overflow-hidden rounded-lg border"
          >
            <button
              type="button"
              class="hover:bg-secondary/20 flex w-full items-center gap-2 px-3 py-3 text-left text-sm font-medium transition-colors"
              aria-expanded={showRuntimeInputAdvanced}
              aria-controls="runtime-input-advanced-panel"
              on:click={() => (showRuntimeInputAdvanced = !showRuntimeInputAdvanced)}
            >
              <IconChevronRight
                class="size-3.5 shrink-0 transition-transform duration-200 {showRuntimeInputAdvanced
                  ? 'rotate-90'
                  : ''}"
              />
              {m.flow_runtime_input_more_settings()}
            </button>
            {#if showRuntimeInputAdvanced}
              <div
                id="runtime-input-advanced-panel"
                class="border-default/70 border-t px-3 pt-3 pb-3"
                transition:slide={{ duration: 200 }}
              >
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
                      on:input={(event) =>
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
                      on:input={(event) =>
                        updateRuntimeInputSettings({
                          max_files:
                            event.currentTarget.value.trim().length > 0
                              ? Number(event.currentTarget.value)
                              : null
                        })}
                    />
                  </div>

                  <div class="flex flex-col gap-2 md:col-span-2">
                    <label class="text-sm font-medium">
                      {m.flow_runtime_input_mimetypes_label()}
                    </label>
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
                          on:click={() => toggleMimePreset(preset.mime)}
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
                              !getMimePresetsForFormat(
                                runtimeInputConfig.input_format
                              ).some((p) => p.mime === mt)
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
                            !getMimePresetsForFormat(
                              runtimeInputConfig.input_format
                            ).some((p) => p.mime === mt)
                        )
                        .join(", ")}
                      disabled={isPublished}
                      on:input={(event) => {
                        const presetMimes =
                          runtimeInputConfig.accepted_mimetypes_override.filter((mt) =>
                            getMimePresetsForFormat(runtimeInputConfig.input_format).some(
                              (p) => p.mime === mt
                            )
                          );
                        const customMimes = parseMimeOverrideDraft(
                          event.currentTarget.value
                        );
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
            {/if}
          </div>
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
    isPublished={isPublished}
    {flowId}
    on:configChange={(e) => dispatch("httpConfigChange", { config: e.detail.config })}
  />
{/if}

{#if step.input_type === "audio"}
  <div
    class={`mb-3 flex items-center justify-between rounded-[1rem] border px-5 py-4 ${
      !transcriptionEnabled || !transcriptionModelConfigured
        ? "border-warning-default/30 bg-warning-dimmer/50"
        : "border-accent-default/15 bg-accent-default/5"
    }`}
  >
    <div class="flex items-center gap-2.5">
      <IconMicrophone
        class={`size-4 shrink-0 ${
          !transcriptionEnabled || !transcriptionModelConfigured
            ? "text-warning-stronger/70"
            : "text-accent-default"
        }`}
      />
      <span
        class={`text-[0.8125rem] font-medium ${
          !transcriptionEnabled || !transcriptionModelConfigured
            ? "text-warning-stronger"
            : "text-primary"
        }`}
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
        class={`flex items-center gap-1 text-xs font-medium transition-colors ${
          !transcriptionEnabled || !transcriptionModelConfigured
            ? "text-warning-stronger/80 hover:text-warning-stronger"
            : "text-accent-default hover:text-accent-stronger"
        }`}
        on:click={() => dispatch("openTranscriptionSettings")}
      >
        {m.edit()}
        {m.flow_stage_transcription()}
        <IconChevronRight class="size-3.5" />
      </button>
    </div>
{/if}
