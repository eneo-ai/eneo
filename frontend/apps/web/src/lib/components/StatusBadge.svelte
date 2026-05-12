<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts" module>
  export type StatusTone =
    | "positive"
    | "warning"
    | "negative"
    | "info"
    | "neutral"
    | "pine"
    | "amethyst"
    | "moss";

  const TONE_TO_LABEL_CLASS: Record<StatusTone, string> = {
    positive: "label-green",
    warning: "label-yellow",
    negative: "label-red",
    info: "label-blue",
    neutral: "label-grey",
    pine: "label-pine",
    amethyst: "label-amethyst",
    moss: "label-moss"
  };
</script>

<script lang="ts">
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { cn } from "$lib/utils.js";
  import type { Snippet } from "svelte";

  type Props = {
    tone?: StatusTone;
    tooltip?: string | null | undefined;
    capitalize?: boolean;
    monospaced?: boolean;
    class?: string;
    children: Snippet;
  };

  let {
    tone = "neutral",
    tooltip,
    capitalize = false,
    monospaced = false,
    class: className,
    children
  }: Props = $props();

  const baseClasses = $derived(
    cn(
      "border-label-default bg-label-dimmer text-label-stronger",
      "inline-flex h-auto items-center rounded-md border px-2.5 py-1 text-sm font-medium leading-5",
      TONE_TO_LABEL_CLASS[tone],
      capitalize && "capitalize",
      monospaced && "font-mono",
      className
    )
  );
</script>

{#if tooltip}
  <Tooltip.Root>
    <Tooltip.Trigger>
      {#snippet child({ props })}
        <Badge {...props} variant="outline" class={baseClasses}>
          {@render children()}
        </Badge>
      {/snippet}
    </Tooltip.Trigger>
    <Tooltip.Content class="max-w-xs whitespace-pre-line">
      {tooltip}
    </Tooltip.Content>
  </Tooltip.Root>
{:else}
  <Badge variant="outline" class={baseClasses}>
    {@render children()}
  </Badge>
{/if}
