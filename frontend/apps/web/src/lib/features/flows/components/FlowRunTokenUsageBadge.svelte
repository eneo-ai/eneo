<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import {
    buildFlowRunTokenUsageView,
    formatFlowRunTokenCount,
    type FlowRunTokenUsagePayload
  } from "./flowRunTokenUsage";

  interface Props {
    tokenUsage?: FlowRunTokenUsagePayload | null;
    interactive?: boolean;
    emptyPlaceholder?: boolean;
  }

  let { tokenUsage = null, interactive = true, emptyPlaceholder = false }: Props = $props();

  const usage = $derived.by(() => buildFlowRunTokenUsageView(tokenUsage));

  function formatCompact(value: number): string {
    return formatFlowRunTokenCount(value, getLocale(), { compact: true });
  }

  function formatFull(value: number): string {
    return formatFlowRunTokenCount(value, getLocale());
  }

  function badgeLabel(total: number): string {
    return m.flow_run_tokens_badge({ count: formatCompact(total) });
  }
</script>

{#if usage}
  {#if interactive}
    <Popover.Root>
      <Popover.Trigger>
        {#snippet child({ props })}
          <button
            {...props}
            type="button"
            class="focus-visible:ring-accent-default/30 rounded-full focus-visible:ring-2 focus-visible:outline-none"
            aria-label={m.flow_run_token_usage_title()}
          >
            <Badge
              variant="outline"
              class="bg-secondary/60 text-muted hover:bg-secondary h-5 cursor-help px-1.5 text-[10.5px] font-medium tabular-nums transition-colors"
            >
              {badgeLabel(usage.total)}
            </Badge>
          </button>
        {/snippet}
      </Popover.Trigger>
      <Popover.Content align="start" class="w-72 gap-3">
        <Popover.Header>
          <Popover.Title>{m.flow_run_token_usage_title()}</Popover.Title>
          <Popover.Description class="text-xs leading-relaxed">
            {m.flow_run_token_usage_description()}
          </Popover.Description>
        </Popover.Header>

        <dl class="grid grid-cols-[1fr_auto] gap-x-4 gap-y-2 text-xs">
          <dt class="text-muted">{m.flow_run_tokens_total()}</dt>
          <dd class="text-primary font-mono tabular-nums">{formatFull(usage.total)}</dd>

          <dt class="text-muted">{m.flow_run_tokens_input()}</dt>
          <dd class="text-primary font-mono tabular-nums">{formatFull(usage.input)}</dd>

          <dt class="text-muted">{m.flow_run_tokens_output()}</dt>
          <dd class="text-primary font-mono tabular-nums">{formatFull(usage.output)}</dd>
        </dl>

        <div
          class="border-default bg-secondary/40 text-muted rounded-md border px-2.5 py-2 text-xs leading-relaxed"
        >
          {m.flow_run_token_usage_provider_note()}
        </div>
      </Popover.Content>
    </Popover.Root>
  {:else}
    <Badge
      variant="outline"
      class="bg-secondary/60 text-muted h-5 shrink-0 px-1.5 text-[10.5px] font-medium tabular-nums"
      aria-label={m.flow_run_token_usage_title()}
    >
      {badgeLabel(usage.total)}
    </Badge>
  {/if}
{:else if emptyPlaceholder}
  <span class="text-muted text-sm" aria-hidden="true">-</span>
{/if}
