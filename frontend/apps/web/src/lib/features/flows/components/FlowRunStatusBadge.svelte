<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { getFlowRunStatusView } from "./flowRunStatusPresentation";

  interface Props {
    status: string;
    class?: string;
    size?: "xs" | "sm" | "md";
    showDot?: boolean;
    pulsing?: boolean;
  }

  let { status, class: className = "", size = "sm", showDot = true, pulsing }: Props = $props();

  const view = $derived(
    getFlowRunStatusView(status, {
      completed: m.flow_run_status_completed,
      failed: m.flow_run_status_failed,
      queued: m.flow_run_status_queued,
      running: m.flow_run_status_running,
      cancelled: m.flow_run_status_cancelled
    })
  );
  const textClass = $derived(size === "xs" ? "text-[11px]" : size === "md" ? "text-sm" : "text-xs");
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
