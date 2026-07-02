<script lang="ts">
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
</script>

<Settings.Group title={m.flow_step_output_section()}>
  <Settings.Row title={m.flow_step_output_type()} description={m.flow_step_output_format_desc()}>
    <div class="flex flex-col gap-2">
      <select
        class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
        value={step.output_type}
        disabled={isPublished}
        onchange={(e) => onOutputTypeChange?.({ value: e.currentTarget.value })}
      >
        {#each availableOutputTypes as t (t.value)}
          <option value={t.value}>{t.label}</option>
        {/each}
      </select>
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
          <Alert.Description class="text-accent-stronger/80 text-xs leading-relaxed">
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
    <select
      class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
      value={step.output_mode}
      disabled={isPublished}
      onchange={(e) => onOutputModeChange?.({ value: e.currentTarget.value })}
    >
      {#each availableOutputModes as mode (mode.value)}
        <option value={mode.value}>{mode.label}</option>
      {/each}
    </select>
  </Settings.Row>

  {#if supportsCitationMode}
    <Settings.Row
      title={m.flow_step_citation_mode()}
      description={m.flow_step_citation_mode_desc()}
    >
      <div class="flex flex-col gap-2">
        <select
          class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
          value={citationMode}
          disabled={isPublished}
          onchange={(e) =>
            onCitationModeChange?.({
              value:
                e.currentTarget.value === FLOW_CITATION_MODE_INLINE_INREF_SIDECAR
                  ? FLOW_CITATION_MODE_INLINE_INREF_SIDECAR
                  : FLOW_CITATION_MODE_OFF
            })}
        >
          <option value={FLOW_CITATION_MODE_OFF}>{m.flow_step_citation_mode_off()}</option>
          <option value={FLOW_CITATION_MODE_INLINE_INREF_SIDECAR}>
            {m.flow_step_citation_mode_inline_inref_sidecar()}
          </option>
        </select>
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
        <input
          class="border-default bg-primary focus-within:border-accent-default focus-within:ring-accent-default/20 hover:border-stronger w-full rounded-xl border px-3.5 py-2.5 text-sm shadow-[0_2px_8px_-4px_rgba(0,0,0,0.05)] transition-shadow focus-within:ring-2 focus-visible:outline-none disabled:opacity-50"
          value={step.output_config?.url ?? ""}
          disabled={isPublished}
          oninput={(e) => onWebhookUrlChange?.({ value: e.currentTarget.value })}
          placeholder="https://..."
        />
      </Settings.Row>
    {/if}
  {/if}
</Settings.Group>

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
