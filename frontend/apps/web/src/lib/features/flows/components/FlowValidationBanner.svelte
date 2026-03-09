<script lang="ts">
  import type { FlowStep } from "@intric/intric-js";
  import { IconInfo } from "@intric/icons/info";
  import { fade, slide } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";
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

  function toggleExpanded() {
    isExpanded = !isExpanded;
  }

  function handleNavigate(stepId: string | undefined) {
    if (stepId && onNavigateToStep) {
      onNavigateToStep(stepId);
    }
  }
</script>

{#if hasErrors}
  <div
    class="border-negative-default/40 border-b"
    role="alert"
    aria-live="polite"
    transition:fade={{ duration: 200 }}
  >
    <button
      type="button"
      class="bg-negative-dimmer flex w-full items-center gap-2 px-4 py-2 text-sm text-negative-stronger transition-colors hover:bg-negative-dimmer/80"
      on:click={toggleExpanded}
      aria-expanded={isExpanded}
      aria-controls="flow-validation-details"
    >
      <IconInfo class="size-4 shrink-0" />
      <span class="flex-1 text-left"
        >{m.flow_validation_issues({ count: String(errorCount) })}</span
      >
      <svg
        class="size-4 shrink-0 transition-transform duration-200"
        class:rotate-180={isExpanded}
        viewBox="0 0 16 16"
        fill="none"
        stroke="currentColor"
        stroke-width="2"
        stroke-linecap="round"
        stroke-linejoin="round"
      >
        <path d="M4 6l4 4 4-4" />
      </svg>
    </button>

    {#if isExpanded}
      <div
        id="flow-validation-details"
        class="bg-negative-dimmer/50 flex flex-col gap-2 px-4 py-3"
        transition:slide={{ duration: 200 }}
      >
        {#each displayIssues as issue (issue.key)}
          <div
            class="bg-default flex items-start gap-3 rounded-lg border border-negative-default/20 px-3 py-2.5"
          >
            {#if issue.stepOrder != null}
              <span
                class="bg-negative-dimmer text-negative-stronger flex size-6 shrink-0 items-center justify-center rounded-full text-xs font-semibold"
              >
                {issue.stepOrder}
              </span>
            {/if}
            <div class="flex min-w-0 flex-1 flex-col gap-1">
              {#if issue.stepName}
                <span class="text-sm font-semibold">{issue.stepName}</span>
              {/if}
              <span class="text-secondary text-sm">{issue.message}</span>
            </div>
            {#if issue.stepId && onNavigateToStep}
              <button
                type="button"
                class="text-accent-default hover:bg-accent-dimmer shrink-0 rounded-md border border-current px-2.5 py-1 text-xs font-medium transition-colors"
                on:click|stopPropagation={() => handleNavigate(issue.stepId)}
              >
                {m.flow_validation_go_to_step()}
              </button>
            {/if}
          </div>
        {/each}
      </div>
    {/if}
  </div>
{/if}
