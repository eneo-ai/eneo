<script lang="ts">
  import FlowStepSection from "$lib/features/flows/components/FlowStepSection.svelte";
  import { Settings } from "$lib/components/layout";
  import { m } from "$lib/paraglide/messages";
  import {
    FLOW_CITATION_MODE_INLINE_INREF_SIDECAR,
    FLOW_CITATION_MODE_OFF,
    resolveFlowCitationMode,
    supportsFlowCitationMode,
    type FlowCitationMode
  } from "$lib/features/flows/flowCitationMode";
  import type { FlowStep } from "@eneo/eneo-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import CircleAlert from "lucide-svelte/icons/circle-alert";
  import {
    getOutputModeCompatibilityIssue,
    type OutputModeCompatibilityIssue,
    type SelectableOutputOption
  } from "$lib/features/flows/flowStepTypes";
  import { getOutputHintText } from "./flowStepEditHelpers";
  import HttpConfigPanel from "./http/HttpConfigPanel.svelte";
  import { parseHttpAuthoredConfig, type HttpAuthoredConfig } from "./http/httpConfigTypes";
  import { createDefaultHttpConfig } from "./http/httpConfigDefaults";
  import type { FlowOutputHintKind } from "$lib/features/flows/flowStepPresentation";

  let {
    step,
    isPublished,
    isAdvancedMode,
    availableOutputTypes,
    availableOutputModes,
    flowId = "",
    outputHintKind,
    embedded = false,
    onOutputTypeChange,
    onOutputModeChange,
    onWebhookUrlChange,
    onHttpConfigChange,
    onCitationModeChange,
    onSwitchToTemplateFill
  }: {
    step: FlowStep;
    isPublished: boolean;
    isAdvancedMode: boolean;
    availableOutputTypes: SelectableOutputOption<FlowStep["output_type"]>[];
    availableOutputModes: SelectableOutputOption<FlowStep["output_mode"]>[];
    flowId?: string;
    outputHintKind: FlowOutputHintKind | null;
    embedded?: boolean;
    onOutputTypeChange?: (detail: { value: string }) => void;
    onOutputModeChange?: (detail: { value: string }) => void;
    onWebhookUrlChange?: (detail: { value: string }) => void;
    onHttpConfigChange?: (detail: { config: HttpAuthoredConfig }) => void;
    onCitationModeChange?: (detail: { value: FlowCitationMode }) => void;
    onSwitchToTemplateFill?: () => void;
  } = $props();

  const defaultHttpConfig = $derived(createDefaultHttpConfig("output", "POST"));
  const httpConfig = $derived(
    step.output_mode === "http_post"
      ? parseHttpAuthoredConfig(step.output_config, defaultHttpConfig)
      : defaultHttpConfig
  );
  const citationMode = $derived(resolveFlowCitationMode(step.output_config));
  const supportsCitationMode = $derived(supportsFlowCitationMode(step));
  const compatibilityIssue = $derived(getOutputModeCompatibilityIssue(step));

  const selectedOutputTypeLabel = $derived(
    availableOutputTypes.find((t) => t.value === step.output_type)?.label ?? step.output_type
  );
  const selectedOutputModeLabel = $derived(
    availableOutputModes.find((mode) => mode.value === step.output_mode)?.label ?? step.output_mode
  );
  const citationModeLabel = $derived(
    citationMode === FLOW_CITATION_MODE_INLINE_INREF_SIDECAR
      ? m.flow_step_citation_mode_inline_inref_sidecar()
      : m.flow_step_citation_mode_off()
  );

  function getCompatibilityIssueText(issue: OutputModeCompatibilityIssue): string {
    switch (issue) {
      case "compose_text_requires_text":
        return m.flow_output_mode_invalid_compose_text();
      case "render_verbatim_requires_text_document":
        return m.flow_output_mode_invalid_render_verbatim();
      case "template_fill_requires_docx":
        return m.flow_output_mode_invalid_template_fill();
      case "transcribe_only_requires_audio_text":
        return m.flow_output_mode_invalid_transcribe_only();
      case "text_document_requires_render_verbatim":
        return m.flow_output_mode_invalid_text_document();
    }
  }
</script>

<FlowStepSection title={embedded ? undefined : m.flow_step_output_section()}>
  <div class="grid gap-5 lg:grid-cols-2 lg:gap-8">
    <div class="flex flex-col gap-2">
      <label class="text-primary text-sm font-medium" for="flow-step-output-type">
        {m.flow_step_output_type()}
      </label>
      <Select.Root
        type="single"
        value={step.output_type}
        disabled={isPublished}
        onValueChange={(value) => onOutputTypeChange?.({ value })}
      >
        <Select.Trigger
          id="flow-step-output-type"
          class="w-full"
          aria-label={m.flow_step_output_type()}
          aria-invalid={compatibilityIssue !== null}
        >
          {selectedOutputTypeLabel}
        </Select.Trigger>
        <Select.Content>
          <Select.Group>
            {#each availableOutputTypes as t (t.value)}
              <Select.Item value={t.value} label={t.label}>
                {t.label}{t.legacyInvalid ? ` — ${m.flow_output_mode_needs_attention()}` : ""}
              </Select.Item>
            {/each}
          </Select.Group>
        </Select.Content>
      </Select.Root>
      {#if getOutputHintText(step.output_mode, outputHintKind)}
        <p class="text-secondary text-[0.8125rem] leading-relaxed" aria-live="polite">
          {getOutputHintText(step.output_mode, outputHintKind)}
        </p>
      {:else}
        <p class="text-secondary text-[0.8125rem] leading-relaxed">
          {m.flow_step_output_format_desc()}
        </p>
      {/if}
    </div>

    <div class="flex flex-col gap-2">
      <label class="text-primary text-sm font-medium" for="flow-step-output-mode">
        {m.flow_step_output_mode()}
      </label>
      <Select.Root
        type="single"
        value={step.output_mode}
        disabled={isPublished}
        onValueChange={(value) => onOutputModeChange?.({ value })}
      >
        <Select.Trigger
          id="flow-step-output-mode"
          class="w-full"
          aria-label={m.flow_step_output_mode()}
          aria-invalid={compatibilityIssue !== null}
        >
          {selectedOutputModeLabel}
        </Select.Trigger>
        <Select.Content>
          <Select.Group>
            {#each availableOutputModes as mode (mode.value)}
              <Select.Item value={mode.value} label={mode.label}>
                {mode.label}{mode.legacyInvalid ? ` — ${m.flow_output_mode_needs_attention()}` : ""}
              </Select.Item>
            {/each}
          </Select.Group>
        </Select.Content>
      </Select.Root>
    </div>
  </div>

  {#if compatibilityIssue}
    <Alert.Root class="border-warning-default/35 bg-warning-dimmer/25 rounded-xl px-4 py-3">
      <CircleAlert class="text-warning-stronger mt-0.5 size-4 shrink-0" aria-hidden="true" />
      <Alert.Title class="text-warning-stronger text-sm font-medium">
        {m.flow_output_mode_needs_attention()}
      </Alert.Title>
      <Alert.Description class="text-warning-stronger text-[0.8125rem] leading-relaxed">
        {getCompatibilityIssueText(compatibilityIssue)}
      </Alert.Description>
    </Alert.Root>
  {/if}

  {#if isAdvancedMode && step.output_type === "docx"}
    <Alert.Root
      class="border-accent-default/20 bg-accent-dimmer/30 mb-4 rounded-xl px-4 py-3"
      role="status"
    >
      <div class="flex flex-col gap-3 md:flex-row md:items-center md:justify-between">
        <div class="space-y-1">
          <Alert.Title class="text-accent-stronger text-sm font-medium">
            {m.flow_template_fill_title()}
          </Alert.Title>
          <Alert.Description class="text-accent-stronger text-xs leading-relaxed">
            {m.flow_template_fill_summary()}
          </Alert.Description>
        </div>
        <Button
          variant="outline"
          size="sm"
          disabled={isPublished}
          onclick={() => onSwitchToTemplateFill?.()}
        >
          {m.flow_output_mode_template_fill()}
        </Button>
      </div>
    </Alert.Root>
  {/if}

  {#if isAdvancedMode && supportsCitationMode}
    <Settings.Row
      title={m.flow_step_citation_mode()}
      description={m.flow_step_citation_mode_desc()}
      density="compact"
    >
      <div class="flex flex-col gap-2">
        <Select.Root
          type="single"
          value={citationMode}
          disabled={isPublished}
          onValueChange={(value) =>
            onCitationModeChange?.({
              value:
                value === FLOW_CITATION_MODE_INLINE_INREF_SIDECAR
                  ? FLOW_CITATION_MODE_INLINE_INREF_SIDECAR
                  : FLOW_CITATION_MODE_OFF
            })}
        >
          <Select.Trigger class="w-full" aria-label={m.flow_step_citation_mode()}>
            {citationModeLabel}
          </Select.Trigger>
          <Select.Content>
            <Select.Group>
              <Select.Item value={FLOW_CITATION_MODE_OFF} label={m.flow_step_citation_mode_off()}>
                {m.flow_step_citation_mode_off()}
              </Select.Item>
              <Select.Item
                value={FLOW_CITATION_MODE_INLINE_INREF_SIDECAR}
                label={m.flow_step_citation_mode_inline_inref_sidecar()}
              >
                {m.flow_step_citation_mode_inline_inref_sidecar()}
              </Select.Item>
            </Select.Group>
          </Select.Content>
        </Select.Root>
        <p class="text-muted text-xs leading-relaxed">
          {m.flow_step_citation_mode_help()}
        </p>
      </div>
    </Settings.Row>
  {/if}

  {#if isAdvancedMode && step.output_mode === "http_post"}
    <!-- Legacy URL-only fallback for configs without authored format -->
    {#if step.output_config && !step.output_config.auth}
      <Settings.Row title={m.flow_step_webhook_url()} description="" density="compact">
        <Input
          value={step.output_config?.url ?? ""}
          disabled={isPublished}
          oninput={(e) => onWebhookUrlChange?.({ value: e.currentTarget.value })}
          placeholder={m.flow_step_output_url_placeholder()}
        />
      </Settings.Row>
    {/if}
  {/if}
</FlowStepSection>

{#if isAdvancedMode && step.output_mode === "http_post" && (step.output_config?.auth || !step.output_config?.url)}
  <HttpConfigPanel
    config={httpConfig}
    direction="output"
    method="POST"
    {isPublished}
    {flowId}
    onConfigChange={(detail) => onHttpConfigChange?.({ config: detail.config })}
  />
{/if}
