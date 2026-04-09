<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { IconInfo } from "@intric/icons/info";
  import { fade, slide } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";
  import { Alert, Collapsible, Badge } from "@eneo/ui";
  import {
    getValidationIssueMessage,
    parseValidationError,
    type ParsedValidationError
  } from "$lib/features/flows/flowStepValidationMessages";

  export let errors: Map<string, string[]>;
  export let steps: FlowStep[] = [];
  export let onNavigateToStep: ((stepId: string) => void) | undefined = undefined;

  export let isExpanded = false;

  $: errorCount = errors.size;
  $: hasErrors = errorCount > 0;

  type DisplayIssue = {
    key: string;
    stepOrder: number | null;
    stepName: string;
    stepId: string | undefined;
    message: string;
  };

  $: displayIssues = (() => {
    const result: DisplayIssue[] = [];
    for (const [key, values] of errors.entries()) {
      const parsed = parseValidationError(key, values);
      if (!parsed) continue;
      result.push(toDisplayIssue(key, parsed));
    }
    return result.sort((a, b) => (a.stepOrder ?? 999) - (b.stepOrder ?? 999));
  })();

  function toDisplayIssue(key: string, parsed: ParsedValidationError): DisplayIssue {
    switch (parsed.kind) {
      case "step": {
        const step = steps.find((s) => s.step_order === parsed.stepOrder);
        return {
          key,
          stepOrder: parsed.stepOrder,
          stepName:
            step?.user_description ||
            m.flow_step_fallback_label({ order: String(parsed.stepOrder) }),
          stepId: step?.id ?? undefined,
          message: getValidationIssueMessage(parsed.code)
        };
      }
      case "assistant": {
        const step = steps.find((s) => s.assistant_id === parsed.assistantId);
        const translated = getValidationIssueMessage(parsed.message);
        return {
          key,
          stepOrder: step?.step_order ?? null,
          stepName:
            step?.user_description ||
            (step ? m.flow_step_fallback_label({ order: String(step.step_order) }) : ""),
          stepId: step?.id ?? undefined,
          message: translated !== parsed.message ? translated : parsed.message
        };
      }
      case "flow": {
        const translated = getValidationIssueMessage(parsed.code);
        return {
          key,
          stepOrder: null,
          stepName: "",
          stepId: undefined,
          message: translated !== parsed.code ? translated : parsed.message
        };
      }
    }
  }

  function handleNavigate(stepId: string | undefined) {
    if (stepId && onNavigateToStep) {
      onNavigateToStep(stepId);
    }
  }
</script>

{#if hasErrors}
  <div role="alert" aria-live="polite" transition:fade={{ duration: 200 }}>
    <Collapsible.Root bind:open={isExpanded}>
      <div class="border-b border-negative-default/30 bg-negative-dimmer/80 backdrop-blur-sm">
        <Collapsible.Trigger class="flex w-full items-center gap-2.5 px-4 py-2.5 text-sm transition-colors hover:bg-negative-dimmer">
          <div class="flex size-5 shrink-0 items-center justify-center rounded-full bg-negative-default/15">
            <IconInfo class="size-3 text-negative-stronger" />
          </div>
          <span class="flex-1 text-left font-medium text-negative-stronger">
            {m.flow_validation_issues({ count: String(errorCount) })}
          </span>
          <svg
            class="size-4 shrink-0 text-negative-stronger/60 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] {isExpanded ? 'rotate-180' : ''}"
            viewBox="0 0 16 16"
            fill="none"
            stroke="currentColor"
            stroke-width="2"
            stroke-linecap="round"
            stroke-linejoin="round"
          >
            <path d="M4 6l4 4 4-4" />
          </svg>
        </Collapsible.Trigger>

        <Collapsible.Content>
          <div class="flex flex-col gap-2 px-4 pb-3" transition:slide={{ duration: 200 }}>
            {#each displayIssues as issue (issue.key)}
              <div class="group flex items-start gap-3 rounded-xl border border-negative-default/15 bg-primary px-4 py-3 shadow-sm transition-shadow hover:shadow-md">
                {#if issue.stepOrder != null}
                  <span class="flex size-7 shrink-0 items-center justify-center rounded-lg bg-negative-dimmer text-xs font-bold text-negative-stronger">
                    {issue.stepOrder}
                  </span>
                {/if}
                <div class="flex min-w-0 flex-1 flex-col gap-0.5">
                  {#if issue.stepName}
                    <span class="text-sm font-semibold tracking-[-0.01em]">{issue.stepName}</span>
                  {/if}
                  <span class="text-[13px] leading-relaxed text-secondary">{issue.message}</span>
                </div>
                {#if issue.stepId && onNavigateToStep}
                  <button
                    type="button"
                    class="shrink-0 rounded-lg border border-accent-default/20 bg-accent-default/5 px-3 py-1.5 text-xs font-medium text-accent-default transition-all duration-200 hover:border-accent-default/40 hover:bg-accent-default/10 hover:shadow-sm active:scale-[0.98]"
                    on:click|stopPropagation={() => handleNavigate(issue.stepId)}
                  >
                    {m.flow_validation_go_to_step()}
                  </button>
                {/if}
              </div>
            {/each}
          </div>
        </Collapsible.Content>
      </div>
    </Collapsible.Root>
  </div>
{/if}
