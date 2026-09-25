<!--
  What the assistant did before answering, for a visitor: one live line
  while it works, then one summary line that opens to a compact timeline.
  No raw tool names, no argument JSON, no result viewer.
-->
<script lang="ts">
  import { Check, ChevronRight, X } from "@lucide/svelte";
  import { m } from "$lib/paraglide/messages";
  import { creditedServers, groupToolSteps, type WidgetToolStep } from "../widgetToolSteps";
  import TypingIndicator from "$lib/features/chat/components/conversation/TypingIndicator.svelte";

  let { steps, working }: { steps: WidgetToolStep[]; working: boolean } = $props();

  const latest = $derived(steps[steps.length - 1]);
  const groups = $derived(groupToolSteps(steps));
  const servers = $derived(creditedServers(steps));
  const failed = $derived(
    steps.some((step) => step.status === "failed" || step.status === "denied")
  );
  // Several steps sum up by what was done; each query is in the list the
  // line opens, so three searches never make one long line.
  const summary = $derived.by(() => {
    const labels = [...new Set(steps.map((step) => step.summary))].join(" · ");
    return steps.length > 1
      ? `${labels} · ${m.internal_tool_steps_count({ count: steps.length })}`
      : labels;
  });
  const expandable = $derived(steps.length > 1 || steps.some((step) => step.detail));
  let open = $state(false);
</script>

<!-- Icons sit on the first line; wrapped text continues under the text, not the icon. -->
<div class="text-secondary flex flex-col gap-1 text-[13px] leading-snug">
  {#if working && latest}
    <div class="flex items-start gap-2">
      <div class="shrink-0 pt-[5px]" aria-hidden="true"><TypingIndicator /></div>
      <span class="min-w-0 break-words" aria-live="polite">
        {latest.label}{latest.detail ? `: ${latest.detail}` : ""}…
      </span>
    </div>
  {:else if expandable}
    <button
      type="button"
      class="hover:text-primary flex w-fit max-w-full items-start gap-1.5 rounded-md text-left"
      aria-expanded={open}
      onclick={() => (open = !open)}
    >
      <ChevronRight
        class={`mt-0.5 size-3.5 shrink-0 transition-transform ${open ? "rotate-90" : ""}`}
        aria-hidden="true"
      />
      {@render outcome()}
      <span class="min-w-0 break-words">{summary}</span>
    </button>
    {#if open}
      <ol class="border-default ml-[7px] flex flex-col gap-1.5 border-l pt-1 pl-3.5">
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
        {#if servers.length > 0}
          <li class="text-muted text-xs">
            {m.widget_activity_via({ server: servers.join(", ") })}
          </li>
        {/if}
      </ol>
    {/if}
  {:else if latest}
    <p class="flex items-start gap-1.5">
      {@render outcome()}
      <span class="min-w-0 break-words">
        {latest.label}{#if latest.via}<span class="text-muted"
            >{` · ${m.widget_activity_via({ server: latest.via })}`}</span
          >{/if}
      </span>
    </p>
  {/if}
</div>

{#snippet outcome()}
  {#if failed}
    <X class="text-negative-default mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
    <span class="sr-only">{m.widget_activity_failed()}: </span>
  {:else}
    <Check class="text-positive-default mt-0.5 size-3.5 shrink-0" aria-hidden="true" />
    <span class="sr-only">{m.widget_activity_done()}: </span>
  {/if}
{/snippet}
