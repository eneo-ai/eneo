<script lang="ts">
  import { useId } from "bits-ui";

  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    total: string;
    input: string;
    output: string;
    note: string;
    estimated?: boolean;
    incomplete?: boolean;
    inputIncomplete?: boolean;
    outputIncomplete?: boolean;
    interactive?: boolean;
  }

  let {
    total,
    input,
    output,
    note,
    estimated = false,
    incomplete = false,
    inputIncomplete = false,
    outputIncomplete = false,
    interactive = true
  }: Props = $props();

  const labelTitleId = useId();
  const badgeLabel = $derived(m.flow_run_tokens_badge({ count: total }));
</script>

{#snippet badge()}
  <Badge
    variant="outline"
    class="bg-secondary/60 text-muted hover:bg-secondary hover:text-primary cursor-help px-2 py-0.5 text-xs font-medium tabular-nums motion-safe:transition-colors motion-safe:duration-150"
  >
    {estimated ? "≈ " : ""}{badgeLabel}
    {#if incomplete}
      <span class="text-warning-stronger">· {m.flow_run_token_usage_incomplete()}</span>
    {/if}
  </Badge>
{/snippet}

{#if interactive}
  <Popover.Root>
    <Popover.Trigger>
      {#snippet child({ props })}
        <button
          {...props}
          type="button"
          class="ring-offset-background focus-visible:ring-accent-default/40 focus-visible:ring-offset-background rounded-full focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none"
        >
          {@render badge()}
        </button>
      {/snippet}
    </Popover.Trigger>
    <Popover.Content align="end" class="w-72 gap-3">
      <Popover.Header>
        <Popover.Title id={labelTitleId}>{m.flow_run_token_usage_title()}</Popover.Title>
      </Popover.Header>

      <dl
        aria-labelledby={labelTitleId}
        class="grid grid-cols-[1fr_auto] items-baseline gap-x-6 gap-y-2 text-sm"
      >
        <dt class="text-secondary">{m.flow_run_tokens_total()}</dt>
        <dd class="text-primary font-semibold tabular-nums">{estimated ? "≈ " : ""}{total}</dd>

        <dt class="text-muted text-xs">{m.flow_run_tokens_input()}</dt>
        <dd class="text-secondary text-xs tabular-nums">
          {estimated ? "≈ " : ""}{input}
          {#if inputIncomplete}
            <span class="text-warning-stronger">· {m.flow_run_token_usage_incomplete()}</span>
          {/if}
        </dd>

        <dt class="text-muted text-xs">{m.flow_run_tokens_output()}</dt>
        <dd class="text-secondary text-xs tabular-nums">
          {estimated ? "≈ " : ""}{output}
          {#if outputIncomplete}
            <span class="text-warning-stronger">· {m.flow_run_token_usage_incomplete()}</span>
          {/if}
        </dd>
      </dl>

      <p class="border-default text-muted border-t pt-3 text-xs leading-relaxed">{note}</p>
    </Popover.Content>
  </Popover.Root>
{:else}
  {@render badge()}
{/if}
