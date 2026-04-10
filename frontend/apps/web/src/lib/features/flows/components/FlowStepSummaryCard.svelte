<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@intric/intric-js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import {
    getInputTypeLabel,
    getOutputTypeLabel,
    getSummarySourceText,
    getSummaryNextChannelText,
    hasAdvancedSettingsActive
  } from "./flowStepEditHelpers";
  import { getHttpSummaryText } from "./http/httpConfigHelpers";
  import type { HttpAuthoredConfig, HttpMethod } from "./http/httpConfigTypes";

  let {
    step,
    summaryModel,
    previousStep,
    isAdvancedMode,
    hasInputTemplateOverride
  }: {
    step: FlowStep;
    summaryModel: {
      usesInputTemplate?: boolean;
      hasKnowledge?: boolean;
      hasAttachments?: boolean;
      downstreamKind?: string;
    } | null;
    previousStep: FlowStep | undefined | null;
    isAdvancedMode: boolean;
    hasInputTemplateOverride: boolean;
  } = $props();

  const httpOutputConfig = $derived(
    step.output_mode === "http_post" && step.output_config?.auth
      ? (step.output_config as unknown as HttpAuthoredConfig)
      : null
  );
  const httpInputConfig = $derived(
    (step.input_source === "http_get" || step.input_source === "http_post") &&
      step.input_config?.auth
      ? (step.input_config as unknown as HttpAuthoredConfig)
      : null
  );
  const httpMethod = $derived((step.input_source === "http_get" ? "GET" : "POST") as HttpMethod);
  const httpSummary = $derived(
    httpOutputConfig
      ? getHttpSummaryText(httpOutputConfig, "POST")
      : httpInputConfig
        ? getHttpSummaryText(httpInputConfig, httpMethod)
        : ""
  );

  const summaryKey = $derived(
    `${getSummarySourceText(step, summaryModel, previousStep)}|${getInputTypeLabel(step.input_type)}|${getOutputTypeLabel(step.output_type)}|${getSummaryNextChannelText(step, summaryModel)}`
  );

  let prevSummaryKey = $state("");
  let gridPulse = $state(false);
  let pulseTimer: ReturnType<typeof setTimeout> | null = null;

  $effect(() => {
    if (summaryKey !== prevSummaryKey) {
      if (prevSummaryKey) {
        gridPulse = true;
        if (pulseTimer) clearTimeout(pulseTimer);
        pulseTimer = setTimeout(() => {
          gridPulse = false;
        }, 700);
      }
      prevSummaryKey = summaryKey;
    }
  });
</script>

<Card.Root class="border-accent-default/18 bg-primary/75 mb-4 rounded-2xl px-4 py-4 sm:px-5">
  <div class="flex flex-wrap items-center gap-2">
    <span class="text-base font-semibold tracking-tight">{m.flow_step_summary_title()}</span>
    {#if summaryModel?.usesInputTemplate}
      <Badge class="bg-accent-dimmer text-accent-stronger">
        {m.flow_step_summary_badge_input_template()}
      </Badge>
    {/if}
    {#if summaryModel?.hasKnowledge}
      <Badge class="bg-hover-dimmer text-secondary">
        {m.flow_step_summary_badge_knowledge()}
      </Badge>
    {/if}
    {#if summaryModel?.hasAttachments}
      <Badge class="bg-hover-dimmer text-secondary">
        {m.flow_step_summary_badge_attachments()}
      </Badge>
    {/if}
    {#if !isAdvancedMode && hasAdvancedSettingsActive(step, hasInputTemplateOverride)}
      <Badge class="bg-warning-dimmer text-warning-stronger">
        {m.flow_step_summary_badge_advanced()}
      </Badge>
    {/if}
  </div>

  <Card.Content
    class="border-default/70 bg-secondary/15 mt-4 grid overflow-hidden rounded-2xl border p-0 sm:grid-cols-2 xl:grid-cols-4 {gridPulse
      ? 'summary-grid-pulse'
      : ''}"
  >
    <div class="border-default/70 min-w-0 border-b px-4 py-3 sm:border-r xl:border-b-0">
      <p class="text-muted text-xs font-semibold tracking-[0.07em] uppercase">
        {m.flow_step_summary_source_label()}
      </p>
      <p class="text-primary mt-1 text-sm">
        {getSummarySourceText(step, summaryModel, previousStep)}
      </p>
    </div>
    <div class="border-default/70 min-w-0 border-b px-4 py-3 xl:border-r xl:border-b-0">
      <p class="text-muted text-xs font-semibold tracking-[0.07em] uppercase">
        {m.flow_step_summary_input_format_label()}
      </p>
      <p class="text-primary mt-1 text-sm">{getInputTypeLabel(step.input_type)}</p>
    </div>
    <div class="border-default/70 min-w-0 border-b px-4 py-3 sm:border-r sm:border-b-0 xl:border-r">
      <p class="text-muted text-xs font-semibold tracking-[0.07em] uppercase">
        {m.flow_step_summary_output_format_label()}
      </p>
      <p class="text-primary mt-1 text-sm">
        {getOutputTypeLabel(step.output_type)}
      </p>
    </div>
    <div class="min-w-0 px-4 py-3">
      <p class="text-muted text-xs font-semibold tracking-[0.07em] uppercase">
        {m.flow_step_summary_next_channel_label()}
      </p>
      <p class="text-primary mt-1 text-sm">{getSummaryNextChannelText(step, summaryModel)}</p>
    </div>
  </Card.Content>
  {#if httpSummary}
    <p class="text-muted mt-2 truncate px-1 font-mono text-xs">{httpSummary}</p>
  {/if}
</Card.Root>

<style>
  @media (prefers-reduced-motion: no-preference) {
    :global(.summary-grid-pulse) {
      animation: summary-pulse 700ms ease-out;
    }
  }

  @keyframes summary-pulse {
    0%,
    12% {
      border-color: var(--accent-default);
      box-shadow: 0 0 0 1px color-mix(in srgb, var(--accent-default) 20%, transparent);
    }
    100% {
      border-color: color-mix(in srgb, var(--border-default) 70%, transparent);
      box-shadow: none;
    }
  }
</style>
