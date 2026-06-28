<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Compact cost chip for a model. Renders the indicative price the admin
  has stored against the model, formatted per 1M tokens for completion +
  embedding models and per audio-minute for transcription. Shows "–"
  with an explanatory tooltip when no cost is on record so admin tables
  surface unpriced models at a glance.

  This is a *display-only* helper — token-rated cost estimation lives
  in `formatModelStats.ts`. Cost values are stored in USD on the backend.
-->

<script lang="ts">
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@eneo/eneo-js";
  import { Tooltip } from "@eneo/ui";
  import {
    formatCostPerMillionTokens,
    formatCostPerMinute,
    type CostFieldValue
  } from "../formatModelStats";
  import { m } from "$lib/paraglide/messages";

  export let model: CompletionModel | EmbeddingModel | TranscriptionModel;
  /** Tighter padding for table cells; default is comfortable for detail panes. */
  export let dense: boolean = false;

  type Pricing =
    | {
        kind: "per_token";
        input: string | null;
        output: string | null;
        raw: { input: CostFieldValue; output: CostFieldValue };
      }
    | { kind: "per_minute"; value: string | null; raw: CostFieldValue };

  function pricingFor(model: CompletionModel | EmbeddingModel | TranscriptionModel): Pricing {
    if ("cost_per_minute" in model) {
      return {
        kind: "per_minute",
        value: formatCostPerMinute(model.cost_per_minute),
        raw: model.cost_per_minute
      };
    }
    const input = "input_cost_per_token" in model ? model.input_cost_per_token : null;
    const output = "output_cost_per_token" in model ? model.output_cost_per_token : null;
    return {
      kind: "per_token",
      input: formatCostPerMillionTokens(input),
      output: formatCostPerMillionTokens(output),
      raw: { input, output }
    };
  }

  $: pricing = pricingFor(model);
  $: hasData =
    pricing.kind === "per_minute"
      ? pricing.value !== null
      : pricing.input !== null || pricing.output !== null;

  $: chipText = (() => {
    if (pricing.kind === "per_minute") {
      return pricing.value ? `${pricing.value}/min` : "–";
    }
    // For embeddings, output_cost_per_token is typically zero. Hide it when
    // missing or if it equals the input price exactly so the chip stays short.
    if (!pricing.input && !pricing.output) return "–";
    if (pricing.input && pricing.output && pricing.input !== pricing.output) {
      return `${pricing.input} / ${pricing.output}`;
    }
    return pricing.input ?? pricing.output ?? "–";
  })();

  $: tooltip = (() => {
    if (!hasData) return m.model_cost_unknown();
    if (pricing.kind === "per_minute") return m.model_cost_tooltip_per_minute();
    return m.model_cost_tooltip_per_million();
  })();
</script>

<Tooltip text={tooltip}>
  <span
    class="
      border-dimmer bg-surface-dimmer text-muted
      inline-flex items-center rounded-md border font-mono tabular-nums
      {dense ? 'px-1.5 py-0 text-[11px]' : 'px-2 py-0.5 text-xs'}
    "
    aria-label={`${tooltip}: ${chipText}`}
  >
    {chipText}
  </span>
</Tooltip>
