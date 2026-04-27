<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import {
    buildAIBuilderTokenUsageView,
    formatAIBuilderTokenCount
  } from "./flowAIBuilderTokenUsage";
  import type { AIBuilderTelemetrySummary } from "./protocol";

  interface Props {
    telemetry?: AIBuilderTelemetrySummary | null;
  }

  let { telemetry = null }: Props = $props();

  const usage = $derived.by(() => buildAIBuilderTokenUsageView(telemetry));

  function formatCompact(value: number): string {
    return formatAIBuilderTokenCount(value, getLocale(), { compact: true });
  }

  function formatFull(value: number): string {
    return formatAIBuilderTokenCount(value, getLocale());
  }

  function modelSummary(model: string | null): string {
    return model ?? m.ai_builder_token_usage_unknown_model();
  }
</script>

{#if usage}
  <Popover.Root>
    <Popover.Trigger>
      {#snippet child({ props })}
        <button
          {...props}
          type="button"
          class="focus-visible:ring-accent-default/30 rounded-full focus-visible:ring-2 focus-visible:outline-none"
          aria-label={m.ai_builder_token_usage_title()}
        >
          <Badge
            variant="outline"
            class="bg-secondary/60 text-muted hover:bg-secondary h-5 cursor-help px-1.5 text-[10.5px] font-medium tabular-nums transition-colors"
          >
            {m.ai_builder_token_usage_badge({ count: formatCompact(usage.total) })}
            {#if usage.estimated}
              <span aria-hidden="true">~</span>
            {/if}
          </Badge>
        </button>
      {/snippet}
    </Popover.Trigger>
    <Popover.Content align="start" class="w-80 gap-3">
      <Popover.Header>
        <Popover.Title>{m.ai_builder_token_usage_title()}</Popover.Title>
        <Popover.Description class="text-xs leading-relaxed">
          {m.ai_builder_token_usage_description()}
        </Popover.Description>
      </Popover.Header>

      <dl class="grid grid-cols-[1fr_auto] gap-x-4 gap-y-2 text-xs">
        <dt class="text-muted">{m.ai_builder_token_usage_total()}</dt>
        <dd class="text-primary font-mono tabular-nums">{formatFull(usage.total)}</dd>

        <dt class="text-muted">{m.ai_builder_token_usage_input()}</dt>
        <dd class="text-primary font-mono tabular-nums">{formatFull(usage.prompt)}</dd>

        <dt class="text-muted">{m.ai_builder_token_usage_output()}</dt>
        <dd class="text-primary font-mono tabular-nums">{formatFull(usage.completion)}</dd>

        <dt class="text-muted">{m.ai_builder_token_usage_calls()}</dt>
        <dd class="text-primary font-mono tabular-nums">{formatFull(usage.llmCalls)}</dd>

        <dt class="text-muted">{m.ai_builder_token_usage_model()}</dt>
        <dd class="text-primary max-w-44 truncate text-right" title={modelSummary(usage.model)}>
          {modelSummary(usage.model)}
        </dd>
      </dl>

      <div
        class="border-default bg-secondary/40 text-muted rounded-md border px-2.5 py-2 text-xs leading-relaxed"
      >
        {#if usage.estimated}
          {m.ai_builder_token_usage_estimated_note()}
        {:else}
          {m.ai_builder_token_usage_provider_note()}
        {/if}
      </div>
    </Popover.Content>
  </Popover.Root>
{/if}
