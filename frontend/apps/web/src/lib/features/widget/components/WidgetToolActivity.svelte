<!--
  What the assistant did before answering, for a visitor: one live line
  while it works, then one summary line that opens to a compact timeline.
  No raw tool names, no argument JSON, no result viewer.
-->
<script lang="ts">
  import { Check, ChevronRight, X } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import { groupToolSteps, stepServers, type WidgetToolStep } from "../widgetToolSteps";
  import TypingIndicator from "$lib/features/chat/components/conversation/TypingIndicator.svelte";

  let { steps, working }: { steps: WidgetToolStep[]; working: boolean } = $props();

  const latest = $derived(steps[steps.length - 1]);
  const groups = $derived(groupToolSteps(steps));
  const failed = $derived(
    steps.some((step) => step.status === "failed" || step.status === "denied")
  );
  const summary = $derived.by(() => {
    const labels = groups.map((group) => group.label).join(" · ");
    return steps.length > 1
      ? `${labels} · ${m.internal_tool_steps_count({ count: steps.length })}`
      : labels;
  });
  const expandable = $derived(steps.length > 1 || steps.some((step) => step.detail));
  let open = $state(false);
</script>

<div class="text-secondary flex flex-col gap-1 text-[13px] leading-tight">
  {#if working && latest}
    <div class="flex items-center gap-2">
      <TypingIndicator />
      <span class="truncate" aria-live="polite">
        {latest.label}{latest.detail ? `: ${latest.detail}` : ""}…
      </span>
    </div>
  {:else if expandable}
    <button
      type="button"
      class="hover:text-primary flex w-fit max-w-full items-center gap-1.5 rounded-md text-left"
      aria-expanded={open}
      onclick={() => (open = !open)}
    >
      <ChevronRight
        class={`size-3.5 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
        aria-hidden="true"
      />
      {#if failed}
        <X class="text-negative-default size-3.5 shrink-0" aria-hidden="true" />
        <span class="sr-only">{m.widget_activity_failed()}: </span>
      {:else}
        <Check class="text-positive-default size-3.5 shrink-0" aria-hidden="true" />
        <span class="sr-only">{m.widget_activity_done()}: </span>
      {/if}
      <span class="truncate">{summary}</span>
    </button>
    {#if open}
      <ol class="border-default ml-[7px] flex flex-col gap-1.5 border-l pl-3.5 pt-1">
        {#each groups as group, groupIndex (groupIndex)}
          <li class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
            <span class="text-primary">{group.label}</span>
            {#each group.steps as step, stepIndex (step.toolCallId ?? stepIndex)}
              {#if step.detail}
                <span
                  class={`border-default rounded-md border px-1.5 text-[11px] leading-5 ${
                    step.status === "failed" || step.status === "denied"
                      ? "text-negative-default line-through"
                      : ""
                  }`}>{step.detail}</span
                >
              {/if}
            {/each}
          </li>
        {/each}
        <li class="text-muted text-xs">
          {m.widget_activity_via({ server: stepServers(steps).join(", ") })}
        </li>
      </ol>
    {/if}
  {:else if latest}
    <div class="flex items-center gap-1.5">
      {#if failed}
        <X class="text-negative-default size-3.5 shrink-0" aria-hidden="true" />
      {:else}
        <Check class="text-positive-default size-3.5 shrink-0" aria-hidden="true" />
      {/if}
      <span class="truncate">{latest.label}</span>
      <span class="text-muted text-xs">{m.widget_activity_via({ server: latest.serverName })}</span>
    </div>
  {/if}
</div>
