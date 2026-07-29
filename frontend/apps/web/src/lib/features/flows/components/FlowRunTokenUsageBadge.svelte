<script lang="ts">
  import { useId } from "bits-ui";

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
  }

  let { tokenUsage = null, interactive = true }: Props = $props();

  const usage = $derived.by(() => buildFlowRunTokenUsageView(tokenUsage));

  const labelTitleId = useId();

  function format(value: number): string {
    return formatFlowRunTokenCount(value, getLocale());
  }

  function badgeLabel(total: number): string {
    return m.flow_run_tokens_badge({ count: format(total) });
  }
</script>

{#if usage.kind === "recorded"}
  {#if interactive}
    <Popover.Root>
      <Popover.Trigger>
        {#snippet child({ props })}
          <button
            {...props}
            type="button"
            class="ring-offset-background focus-visible:ring-accent-default/40 focus-visible:ring-offset-background rounded-full focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
          >
            <Badge
              variant="outline"
              class="bg-secondary/60 text-muted hover:bg-secondary hover:text-primary cursor-help px-2 py-0.5 text-xs font-medium tabular-nums motion-safe:transition-colors motion-safe:duration-150"
            >
              {badgeLabel(usage.total)}
              {#if usage.incomplete}
                <span class="text-warning-stronger">· {m.flow_run_token_usage_incomplete()}</span>
              {/if}
            </Badge>
          </button>
        {/snippet}
      </Popover.Trigger>
      <Popover.Content align="start" class="w-72 gap-3">
        <Popover.Header>
          <Popover.Title id={labelTitleId}>{m.flow_run_token_usage_title()}</Popover.Title>
        </Popover.Header>

        <dl
          aria-labelledby={labelTitleId}
          class="grid grid-cols-[1fr_auto] items-baseline gap-x-6 gap-y-2 text-sm"
        >
          <dt class="text-secondary">{m.flow_run_tokens_total()}</dt>
          <dd class="text-primary font-semibold tabular-nums">{format(usage.total)}</dd>

          <dt class="text-muted text-xs">{m.flow_run_tokens_input()}</dt>
          <dd class="text-secondary text-xs tabular-nums">
            {format(usage.input)}
            {#if usage.inputIncomplete}
              <span class="text-warning-stronger">· {m.flow_run_token_usage_incomplete()}</span>
            {/if}
          </dd>

          <dt class="text-muted text-xs">{m.flow_run_tokens_output()}</dt>
          <dd class="text-secondary text-xs tabular-nums">
            {format(usage.output)}
            {#if usage.outputIncomplete}
              <span class="text-warning-stronger">· {m.flow_run_token_usage_incomplete()}</span>
            {/if}
          </dd>
        </dl>

        <p class="border-default text-muted border-t pt-3 text-xs leading-relaxed">
          {m.flow_run_token_usage_provider_note()}
        </p>
      </Popover.Content>
    </Popover.Root>
  {:else}
    <Badge
      variant="outline"
      class="bg-secondary/60 text-muted shrink-0 px-2 py-0.5 text-xs font-medium tabular-nums"
    >
      {badgeLabel(usage.total)}
      {#if usage.incomplete}
        <span class="text-warning-stronger">· {m.flow_run_token_usage_incomplete()}</span>
      {/if}
    </Badge>
  {/if}
{:else}
  <span class="text-muted text-xs">{m.flow_run_token_usage_not_recorded()}</span>
{/if}
