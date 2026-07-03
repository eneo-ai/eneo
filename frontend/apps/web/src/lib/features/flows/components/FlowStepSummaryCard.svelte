<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import type { FlowStep } from "@eneo/eneo-js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { CircleAlert } from "lucide-svelte";
  import {
    getInputTypeLabel,
    getOutputTypeLabel,
    getSummarySourceText,
    hasAdvancedSettingsActive
  } from "./flowStepEditHelpers";
  import { getStepAiWork } from "$lib/features/flows/flowStepEditorPresentation";
  import { createDefaultHttpConfig } from "./http/httpConfigDefaults";
  import { getHttpSummaryText } from "./http/httpConfigHelpers";
  import { parseHttpAuthoredConfig, type HttpMethod } from "./http/httpConfigTypes";

  let {
    step,
    summaryModel,
    previousStep,
    isAdvancedMode,
    hasInputTemplateOverride,
    aiInstructionPresent,
    onFixInstruction
  }: {
    step: FlowStep;
    summaryModel: {
      usesInputTemplate?: boolean;
      downstreamKind?: string;
    } | null;
    previousStep: FlowStep | undefined | null;
    isAdvancedMode: boolean;
    hasInputTemplateOverride: boolean;
    // Whether the step's AI instruction is filled. `null` means the assistant
    // is still loading, so the capsule stays neutral instead of claiming the
    // instruction is missing.
    aiInstructionPresent: boolean | null;
    onFixInstruction?: () => void;
  } = $props();

  const source = $derived(getSummarySourceText(step, summaryModel, previousStep));
  const aiWork = $derived(getStepAiWork(step, { instructionPresent: aiInstructionPresent }));
  const nextChannel = $derived(
    step.output_mode === "transcribe_only"
      ? m.flow_step_summary_next_channel_transcript()
      : summaryModel?.downstreamKind === "text_and_structured"
        ? m.flow_step_summary_next_channel_text_and_structured_short()
        : m.flow_step_summary_next_channel_text_short()
  );

  const httpMethod = $derived((step.input_source === "http_get" ? "GET" : "POST") as HttpMethod);
  const httpOutputConfig = $derived(
    step.output_mode === "http_post"
      ? parseHttpAuthoredConfig(step.output_config, createDefaultHttpConfig("output", "POST"))
      : null
  );
  const httpInputConfig = $derived(
    step.input_source === "http_get" || step.input_source === "http_post"
      ? parseHttpAuthoredConfig(step.input_config, createDefaultHttpConfig("input", httpMethod))
      : null
  );
  const httpSummary = $derived(
    httpOutputConfig
      ? getHttpSummaryText(httpOutputConfig, "POST")
      : httpInputConfig
        ? getHttpSummaryText(httpInputConfig, httpMethod)
        : ""
  );
</script>

<div
  class="border-default/60 bg-secondary/12 mb-4 rounded-xl border px-4 py-3"
  style="font-variant-numeric: tabular-nums"
  aria-live="polite"
  aria-atomic="true"
>
  <div class="flex flex-wrap items-center gap-x-2 gap-y-1.5 text-sm leading-snug">
    <span class="text-secondary min-w-0 truncate" title={source}>
      <span class="text-primary font-medium">{source}</span> · {getInputTypeLabel(step.input_type)}
    </span>

    <span class="text-muted" aria-hidden="true">&rarr;</span>

    {#if aiWork.missing}
      <button
        type="button"
        class="text-warning-stronger hover:text-warning-stronger/80 focus-visible:ring-warning-default/40 inline-flex items-center gap-1 rounded font-medium underline decoration-dotted underline-offset-2 focus-visible:ring-2 focus-visible:outline-none"
        onclick={() => onFixInstruction?.()}
      >
        <CircleAlert class="size-3.5 shrink-0" aria-hidden="true" />{aiWork.text}
      </button>
    {:else}
      <span class="text-primary font-medium">{aiWork.text}</span>
    {/if}

    <span class="text-muted" aria-hidden="true">&rarr;</span>

    <span class="text-secondary">
      <span class="text-primary font-medium">{getOutputTypeLabel(step.output_type)}</span>
      · {m.flow_capsule_next()}: {nextChannel}
    </span>

    {#if !isAdvancedMode && hasAdvancedSettingsActive(step, hasInputTemplateOverride)}
      <Badge
        variant="outline"
        class="border-warning-default/25 bg-warning-dimmer/50 text-warning-stronger ml-auto text-[11px]"
      >
        {m.flow_step_summary_badge_advanced()}
      </Badge>
    {/if}
  </div>

  {#if httpSummary}
    <p class="text-muted mt-1.5 truncate font-mono text-xs">
      {httpSummary}
    </p>
  {/if}
</div>
