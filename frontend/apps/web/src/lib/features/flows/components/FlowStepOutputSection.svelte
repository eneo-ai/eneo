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
    availableOutputTypes: Array<{ value: string; label: string }>;
    availableOutputModes: Array<{ value: string; label: string }>;
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

  // Plain-language reassurance for document outputs — the "vidarebefordra" mode
  // label doesn't make clear that a file is produced.
  const documentHelperText = $derived(
    step.output_mode === "pass_through" &&
      (step.output_type === "pdf" || step.output_type === "docx")
      ? step.output_type === "pdf"
        ? m.flow_output_document_helper_pdf()
        : m.flow_output_document_helper_word()
      : ""
  );
</script>

<FlowStepSection title={embedded ? undefined : m.flow_step_output_section()}>
  <Settings.Row title={m.flow_step_output_type()} description={m.flow_step_output_format_desc()}>
    <div class="flex flex-col gap-2">
      <Select.Root
        type="single"
        value={step.output_type}
        disabled={isPublished}
        onValueChange={(value) => onOutputTypeChange?.({ value })}
      >
        <Select.Trigger class="w-full" aria-label={m.flow_step_output_type()}>
          {selectedOutputTypeLabel}
        </Select.Trigger>
        <Select.Content>
          <Select.Group>
            {#each availableOutputTypes as t (t.value)}
              <Select.Item value={t.value} label={t.label}>{t.label}</Select.Item>
            {/each}
          </Select.Group>
        </Select.Content>
      </Select.Root>
      {#if getOutputHintText(step.output_mode, outputHintKind)}
        <p class="text-muted text-xs leading-relaxed" aria-live="polite">
          {getOutputHintText(step.output_mode, outputHintKind)}
        </p>
      {/if}
    </div>
  </Settings.Row>

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

  <Settings.Row title={m.flow_step_output_mode()} description="">
    <div class="flex flex-col gap-2">
      <Select.Root
        type="single"
        value={step.output_mode}
        disabled={isPublished}
        onValueChange={(value) => onOutputModeChange?.({ value })}
      >
        <Select.Trigger class="w-full" aria-label={m.flow_step_output_mode()}>
          {selectedOutputModeLabel}
        </Select.Trigger>
        <Select.Content>
          <Select.Group>
            {#each availableOutputModes as mode (mode.value)}
              <Select.Item value={mode.value} label={mode.label}>{mode.label}</Select.Item>
            {/each}
          </Select.Group>
        </Select.Content>
      </Select.Root>
      {#if documentHelperText}
        <p class="text-muted text-xs leading-relaxed">{documentHelperText}</p>
      {/if}
    </div>
  </Settings.Row>

  {#if supportsCitationMode}
    <Settings.Row
      title={m.flow_step_citation_mode()}
      description={m.flow_step_citation_mode_desc()}
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

  {#if step.output_mode === "http_post"}
    <!-- Legacy URL-only fallback for configs without authored format -->
    {#if step.output_config && !step.output_config.auth}
      <Settings.Row title={m.flow_step_webhook_url()} description="">
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

{#if step.output_mode === "http_post" && (step.output_config?.auth || !step.output_config?.url)}
  <HttpConfigPanel
    config={httpConfig}
    direction="output"
    method="POST"
    {isPublished}
    {flowId}
    onConfigChange={(detail) => onHttpConfigChange?.({ config: detail.config })}
  />
{/if}
