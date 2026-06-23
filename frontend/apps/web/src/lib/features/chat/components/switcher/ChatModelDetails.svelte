<script lang="ts">
  import type { CompletionModel } from "@intric/intric-js";
  import { Brain, Eye, Wrench } from "lucide-svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { formatCostPerMillionTokens } from "$lib/features/ai-models/formatModelStats";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { getAppContext } from "$lib/core/AppContext";
  import * as ModelSelector from "$lib/components/ai-elements/model-selector/index.js";

  type Props = {
    model: CompletionModel;
  };

  let { model }: Props = $props();

  // Org admins can hide model prices from users; default to showing them.
  const {
    state: { tenant }
  } = getAppContext();
  const showPricing = $derived($tenant.show_model_pricing !== false);

  // Null when the model has no cost on record; the row is then dropped entirely
  // rather than showing a placeholder.
  const inputPrice = $derived(formatCostPerMillionTokens(model.input_cost_per_token));
  const outputPrice = $derived(formatCostPerMillionTokens(model.output_cost_per_token));
  const contextWindow = $derived(
    m.model_selector_context_value({
      tokens: new Intl.NumberFormat(getLocale() === "sv" ? "sv-SE" : "en-US").format(
        model.max_input_tokens
      )
    })
  );
  const description = $derived(model.description?.trim() || m.model_selector_no_description());
</script>

<aside
  class="bg-popover/95 ring-foreground/10 no-scrollbar hidden max-h-[22.25rem] w-80 flex-col overflow-y-auto rounded-xl p-4 shadow-lg ring-1 backdrop-blur-xl sm:flex"
  aria-label={`${m.model_info_for()} ${model.nickname ?? model.name}`}
>
  <div class="flex items-center gap-2.5">
    <ModelSelector.Logo provider={model.org ?? model.provider_type} class="size-5" />
    <div class="min-w-0">
      <h3 class="truncate text-sm font-semibold">{model.nickname ?? model.name}</h3>
      <p class="text-muted-foreground truncate text-xs">
        {model.org ?? model.provider_name ?? model.provider_type ?? ""}
      </p>
    </div>
  </div>

  <p class="text-muted-foreground mt-3 text-[13px] leading-5">{description}</p>

  <dl class="mt-3 divide-y text-xs">
    <div class="flex items-center justify-between gap-4 py-2.5">
      <dt class="text-muted-foreground">{m.model_context_label()}</dt>
      <dd class="text-right text-[13px] font-medium tabular-nums">{contextWindow}</dd>
    </div>
    {#if showPricing && inputPrice}
      <div class="flex items-center justify-between gap-4 py-2.5">
        <dt class="text-muted-foreground">{m.model_selector_input_price()}</dt>
        <dd class="text-right text-[13px] font-medium tabular-nums">
          {inputPrice}
          <span class="text-muted-foreground font-normal">
            / {m.model_selector_million_tokens()}
          </span>
        </dd>
      </div>
    {/if}
    {#if showPricing && outputPrice}
      <div class="flex items-center justify-between gap-4 py-2.5">
        <dt class="text-muted-foreground">{m.model_selector_output_price()}</dt>
        <dd class="text-right text-[13px] font-medium tabular-nums">
          {outputPrice}
          <span class="text-muted-foreground font-normal">
            / {m.model_selector_million_tokens()}
          </span>
        </dd>
      </div>
    {/if}
  </dl>

  {#if model.vision || model.reasoning || model.supports_tool_calling}
    <div class="mt-3">
      <p class="text-muted-foreground mb-2 text-[10px] font-semibold tracking-wider uppercase">
        {m.model_detail_capabilities()}
      </p>
      <div class="flex flex-wrap gap-1.5">
        {#if model.vision}
          <Badge variant="outline" class="bg-muted/40 h-6 border-0 px-2 text-[11px]">
            <Eye aria-hidden="true" />
            {m.model_label_vision()}
          </Badge>
        {/if}
        {#if model.reasoning}
          <Badge variant="outline" class="bg-muted/40 h-6 border-0 px-2 text-[11px]">
            <Brain aria-hidden="true" />
            {m.model_label_reasoning()}
          </Badge>
        {/if}
        {#if model.supports_tool_calling}
          <Badge variant="outline" class="bg-muted/40 h-6 border-0 px-2 text-[11px]">
            <Wrench aria-hidden="true" />
            {m.model_label_tool_calling()}
          </Badge>
        {/if}
      </div>
    </div>
  {/if}
</aside>
