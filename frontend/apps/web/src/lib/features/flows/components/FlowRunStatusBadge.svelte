<script lang="ts">
  import { flowRunStatusTranslations } from "./flowRunStatusLabel";
  import { getFlowRunStatusView } from "./flowRunStatusPresentation";

  interface Props {
    status: string;
    class?: string;
    size?: "xs" | "sm" | "md";
    showDot?: boolean;
    pulsing?: boolean;
  }

  let { status, class: className = "", size = "sm", showDot = true, pulsing }: Props = $props();

  const view = $derived(getFlowRunStatusView(status, flowRunStatusTranslations));
  const textClass = $derived(size === "xs" ? "text-xs" : size === "md" ? "text-sm" : "text-xs");
  const gapClass = $derived(size === "xs" ? "gap-1.5" : "gap-2");
  const shouldPulse = $derived(pulsing ?? view.pulseDot);
  const dotClass = $derived(`${view.dotClass}${shouldPulse ? " animate-pulse" : ""}`);
</script>

<span
  class="{view.textClass} inline-flex items-center font-medium {gapClass} {textClass} {className}"
>
  {#if showDot}
    <span class="{dotClass} size-1.5 shrink-0 rounded-full" aria-hidden="true"></span>
  {/if}
  <span>{view.label}</span>
</span>
