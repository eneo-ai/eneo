<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { IconInfo } from "@intric/icons/info";
  import { fade, slide } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import {
    getValidationIssueMessage,
    parseValidationError,
    type ParsedValidationError
  } from "$lib/features/flows/flowStepValidationMessages";

  let {
    errors,
    steps = [],
    onNavigateToStep,
    isExpanded = $bindable(false)
  }: {
    errors: Map<string, string[]>;
    steps?: FlowStep[];
    onNavigateToStep?: (stepId: string) => void;
    isExpanded?: boolean;
  } = $props();

  const errorCount = $derived(errors.size);
  const hasErrors = $derived(errorCount > 0);

  type DisplayIssue = {
    key: string;
    stepOrder: number | null;
    stepName: string;
    stepId: string | undefined;
    message: string;
  };

  const displayIssues = $derived.by(() => {
    const result: DisplayIssue[] = [];
    for (const [key, values] of errors.entries()) {
      const parsed = parseValidationError(key, values);
      if (!parsed) continue;
      result.push(toDisplayIssue(key, parsed));
    }
    return result.sort((a, b) => (a.stepOrder ?? 999) - (b.stepOrder ?? 999));
  });

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
      <div class="border-negative-default/30 bg-negative-dimmer/80 border-b backdrop-blur-sm">
        <Collapsible.Trigger
          class="hover:bg-negative-dimmer flex w-full items-center gap-2.5 px-4 py-2.5 text-sm transition-colors"
        >
          <div
            class="bg-negative-default/15 flex size-5 shrink-0 items-center justify-center rounded-full"
          >
            <IconInfo class="text-negative-stronger size-3" />
          </div>
          <span class="text-negative-stronger flex-1 text-left font-medium">
            {m.flow_validation_issues({ count: String(errorCount) })}
          </span>
          <svg
            class="text-negative-stronger/60 size-4 shrink-0 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] {isExpanded
              ? 'rotate-180'
              : ''}"
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
              <div
                class="group border-negative-default/15 bg-primary flex items-start gap-3 rounded-xl border px-4 py-3 shadow-sm transition-shadow hover:shadow-md"
              >
                {#if issue.stepOrder != null}
                  <span
                    class="bg-negative-dimmer text-negative-stronger flex size-7 shrink-0 items-center justify-center rounded-lg text-xs font-bold"
                  >
                    {issue.stepOrder}
                  </span>
                {/if}
                <div class="flex min-w-0 flex-1 flex-col gap-0.5">
                  {#if issue.stepName}
                    <span class="text-sm font-semibold tracking-[-0.01em]">{issue.stepName}</span>
                  {/if}
                  <span class="text-secondary text-[13px] leading-relaxed">{issue.message}</span>
                </div>
                {#if issue.stepId && onNavigateToStep}
                  <button
                    type="button"
                    class="border-accent-default/20 bg-accent-default/5 text-accent-default hover:border-accent-default/40 hover:bg-accent-default/10 shrink-0 rounded-lg border px-3 py-1.5 text-xs font-medium transition-all duration-200 hover:shadow-sm active:scale-[0.98]"
                    onclick={(e) => {
                      e.stopPropagation();
                      handleNavigate(issue.stepId);
                    }}
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
