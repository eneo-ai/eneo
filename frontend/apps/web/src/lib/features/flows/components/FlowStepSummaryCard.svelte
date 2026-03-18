<svelte:options runes={false} />

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@intric/intric-js";
  import {
    getInputTypeLabel,
    getOutputTypeLabel,
    getSummarySourceText,
    getSummaryNextChannelText,
    hasAdvancedSettingsActive
  } from "./flowStepEditHelpers";
  import { getHttpSummaryText } from "./http/httpConfigHelpers";
  import type { HttpAuthoredConfig, HttpMethod } from "./http/httpConfigTypes";

  export let step: FlowStep;
  export let summaryModel: {
    usesInputTemplate?: boolean;
    hasKnowledge?: boolean;
    hasAttachments?: boolean;
    downstreamKind?: string;
  } | null;
  export let previousStep: FlowStep | undefined | null;
  export let isAdvancedMode: boolean;
  export let hasInputTemplateOverride: boolean;

  $: httpOutputConfig =
    step.output_mode === "http_post" && step.output_config?.auth
      ? (step.output_config as unknown as HttpAuthoredConfig)
      : null;
  $: httpInputConfig =
    (step.input_source === "http_get" || step.input_source === "http_post") &&
    step.input_config?.auth
      ? (step.input_config as unknown as HttpAuthoredConfig)
      : null;
  $: httpMethod = (
    step.input_source === "http_get" ? "GET" : "POST"
  ) as HttpMethod;
  $: httpSummary =
    httpOutputConfig
      ? getHttpSummaryText(httpOutputConfig, "POST")
      : httpInputConfig
        ? getHttpSummaryText(httpInputConfig, httpMethod)
        : "";
</script>

<div
  class="border-accent-default/18 bg-primary/75 mb-6 rounded-2xl border px-4 py-4 shadow-sm sm:px-5"
>
  <div class="flex flex-wrap items-center gap-2">
    <span class="text-base font-semibold tracking-tight"
      >{m.flow_step_summary_title()}</span
    >
    {#if summaryModel?.usesInputTemplate}
      <span
        class="bg-accent-dimmer text-accent-stronger rounded-full px-2.5 py-1 text-[11px] font-medium"
      >
        {m.flow_step_summary_badge_input_template()}
      </span>
    {/if}
    {#if summaryModel?.hasKnowledge}
      <span
        class="bg-hover-dimmer text-secondary rounded-full px-2.5 py-1 text-[11px] font-medium"
      >
        {m.flow_step_summary_badge_knowledge()}
      </span>
    {/if}
    {#if summaryModel?.hasAttachments}
      <span
        class="bg-hover-dimmer text-secondary rounded-full px-2.5 py-1 text-[11px] font-medium"
      >
        {m.flow_step_summary_badge_attachments()}
      </span>
    {/if}
    {#if !isAdvancedMode && hasAdvancedSettingsActive(step, hasInputTemplateOverride)}
      <span
        class="bg-warning-dimmer text-warning-stronger rounded-full px-2.5 py-1 text-[11px] font-medium"
      >
        {m.flow_step_summary_badge_advanced()}
      </span>
    {/if}
  </div>

  <div
    class="border-default/70 bg-secondary/15 mt-4 grid overflow-hidden rounded-2xl border sm:grid-cols-2 xl:grid-cols-4"
  >
    <div class="border-default/70 min-w-0 border-b px-4 py-3 sm:border-r xl:border-b-0">
      <p class="text-muted text-[10px] font-semibold tracking-[0.07em] uppercase">
        {m.flow_step_summary_source_label()}
      </p>
      <p class="text-primary mt-1 text-sm">{getSummarySourceText(step, summaryModel, previousStep)}</p>
    </div>
    <div class="border-default/70 min-w-0 border-b px-4 py-3 xl:border-r xl:border-b-0">
      <p class="text-muted text-[10px] font-semibold tracking-[0.07em] uppercase">
        {m.flow_step_summary_input_format_label()}
      </p>
      <p class="text-primary mt-1 text-sm">{getInputTypeLabel(step.input_type)}</p>
    </div>
    <div
      class="border-default/70 min-w-0 border-b px-4 py-3 sm:border-r sm:border-b-0 xl:border-r"
    >
      <p class="text-muted text-[10px] font-semibold tracking-[0.07em] uppercase">
        {m.flow_step_summary_output_format_label()}
      </p>
      <p class="text-primary mt-1 text-sm">
        {getOutputTypeLabel(step.output_type)}
      </p>
    </div>
    <div class="min-w-0 px-4 py-3">
      <p class="text-muted text-[10px] font-semibold tracking-[0.07em] uppercase">
        {m.flow_step_summary_next_channel_label()}
      </p>
      <p class="text-primary mt-1 text-sm">{getSummaryNextChannelText(step, summaryModel)}</p>
    </div>
  </div>
  {#if httpSummary}
    <p class="text-muted mt-2 truncate px-1 font-mono text-xs">{httpSummary}</p>
  {/if}
</div>
