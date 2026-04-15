<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import {
    getFlowRunLocalizedStatusLabel,
    getFlowRunStatusColor,
    getFlowRunStatusDotColor
  } from "./flowRunStatusPresentation";

  interface Props {
    /** Run status string: `completed` | `failed` | `queued` | `running` | `cancelled` | `pending`. */
    status: string;
    /** Extra Tailwind classes appended to the wrapper. */
    class?: string;
    /** Text scale — `sm` = `text-xs` (default for tables), `md` = `text-sm` (evidence/cards). */
    size?: "sm" | "md";
  }

  let { status, class: className = "", size = "sm" }: Props = $props();

  const label = $derived(
    getFlowRunLocalizedStatusLabel(status, {
      completed: m.flow_run_status_completed,
      failed: m.flow_run_status_failed,
      queued: m.flow_run_status_queued,
      running: m.flow_run_status_running,
      cancelled: m.flow_run_status_cancelled
    })
  );
  const color = $derived(getFlowRunStatusColor(status));
  const dotColor = $derived(getFlowRunStatusDotColor(status));
  const textClass = $derived(size === "sm" ? "text-xs" : "text-sm");
</script>

<span class="{color} inline-flex items-center gap-2 font-medium {textClass} {className}">
  <span class="{dotColor} size-1.5 shrink-0 rounded-full" aria-hidden="true"></span>
  <span>{label}</span>
</span>
