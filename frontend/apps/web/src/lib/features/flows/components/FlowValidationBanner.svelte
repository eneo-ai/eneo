<script lang="ts">
  import { prefersReducedMotion } from "$lib/core/prefersReducedMotion";
  import type { FlowStep } from "@eneo/eneo-js";
  import { IconInfo } from "@eneo/icons/info";
  import { fade, slide } from "svelte/transition";
  import { m } from "$lib/paraglide/messages";
  import * as Select from "$lib/components/ui/select/index.js";
  import {
    findDanglingBindingReferences,
    repairOptionsFor,
    type DanglingBindingReference
  } from "$lib/features/flows/flowInputBindingRepair";
  import type { FlowInputMaterialOption } from "$lib/features/flows/flowInputBindings";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import {
    getValidationIssueMessage,
    parseValidationError,
    type parseServerValidationIdentity,
    type ParsedValidationError
  } from "$lib/features/flows/flowStepValidationMessages";

  const reducedMotion = prefersReducedMotion();

  let {
    errors,
    steps = [],
    onNavigateToStep,
    repairIssue = null,
    onRepairReference,
    isExpanded = $bindable(false)
  }: {
    errors: Map<string, string[]>;
    steps?: FlowStep[];
    onNavigateToStep?: (stepId: string) => void;
    repairIssue?: ReturnType<typeof parseServerValidationIdentity>;
    onRepairReference?: (detail: {
      stepId: string;
      target: DanglingBindingReference;
      option: FlowInputMaterialOption;
    }) => void;
    isExpanded?: boolean;
  } = $props();

  const errorCount = $derived(errors.size);
  const hasErrors = $derived(errorCount > 0);

  type ReferenceRepair = {
    stepId: string;
    stepLabel: string;
    target: DanglingBindingReference;
    options: FlowInputMaterialOption[];
  };

  type DisplayIssue = {
    key: string;
    stepOrder: number | null;
    stepName: string;
    stepId: string | undefined;
    message: string;
    /** Raw technical sentence, kept for debugging when it adds anything. */
    detail?: string;
    repairs?: ReferenceRepair[];
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
        const translated = getValidationIssueMessage(parsed.code);
        const raw = parsed.detail;
        return {
          key,
          stepOrder: parsed.stepOrder,
          repairs: step ? serverRepairs(key, parsed, step) : [],
          stepName:
            step?.user_description ||
            m.flow_step_fallback_label({ order: String(parsed.stepOrder) }),
          stepId: step?.id ?? undefined,
          // An untranslated code falls back to the raw server sentence
          // rather than showing the bare code.
          message: translated !== parsed.code ? translated : (raw ?? parsed.code),
          detail: raw && translated !== parsed.code && raw !== translated ? raw : undefined
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
        const raw = parsed.detail;
        return {
          key,
          stepOrder: null,
          repairs:
            parsed.code === "deleted-step-reference"
              ? steps.flatMap((step) => repairsForStep(step, { code: parsed.code }))
              : [],
          stepName: "",
          stepId: undefined,
          message: translated !== parsed.code ? translated : (raw ?? parsed.message),
          detail: raw && translated !== parsed.code && raw !== translated ? raw : undefined
        };
      }
    }
  }

  function repairsForStep(
    step: FlowStep,
    issue: Parameters<typeof findDanglingBindingReferences>[1]
  ): ReferenceRepair[] {
    const stepId = step.id;
    if (!stepId || !onRepairReference) return [];
    const targets = findDanglingBindingReferences(step, issue);
    return targets.map((target) => ({
      stepId,
      stepLabel: m.flow_validation_replace_reference_option({
        step: String(step.step_order),
        name: step.user_description || m.flow_step_unnamed()
      }),
      target,
      options: repairOptionsFor(step, steps, target)
    }));
  }

  function serverRepairs(
    key: string,
    issue: Extract<ParsedValidationError, { kind: "step" }>,
    step: FlowStep
  ): ReferenceRepair[] {
    if (
      !key.startsWith("flow:server:") ||
      repairIssue?.code !== issue.code ||
      repairIssue.stepOrder !== issue.stepOrder ||
      ![
        "flow_input_binding_invalid_step_reference",
        "flow_input_binding_unknown_step_order",
        "flow_input_binding_future_step_reference"
      ].includes(issue.code)
    )
      return [];
    return repairsForStep(step, repairIssue);
  }

  function optionLabel(option: FlowInputMaterialOption): string {
    const detail = {
      step: String(option.sourceStepOrder),
      name: option.sourceStepName || m.flow_step_unnamed()
    };
    return option.fieldPath
      ? m.flow_validation_replace_reference_option_field({ ...detail, field: option.fieldPath })
      : m.flow_validation_replace_reference_option(detail);
  }

  function handleNavigate(stepId: string | undefined) {
    if (stepId && onNavigateToStep) {
      onNavigateToStep(stepId);
    }
  }
</script>

{#if hasErrors}
  <div role="alert" aria-live="polite" transition:fade={{ duration: reducedMotion ? 0 : 200 }}>
    <Collapsible.Root bind:open={isExpanded}>
      <div class="border-negative-default/30 bg-negative-dimmer/80 border-b backdrop-blur-sm">
        <Collapsible.Trigger
          class="hover:bg-negative-dimmer flex w-full items-center gap-2.5 px-4 py-2.5 text-sm transition-colors"
          aria-expanded={isExpanded}
          aria-controls="flow-validation-issues"
        >
          <div
            class="bg-negative-default/15 flex size-5 shrink-0 items-center justify-center rounded-full"
          >
            <IconInfo class="text-negative-stronger size-3" aria-hidden="true" />
          </div>
          <span class="text-negative-stronger flex-1 text-left font-medium">
            {m.flow_validation_issues({ count: String(errorCount) })}
          </span>
          <span class="text-negative-stronger/80 hidden text-xs font-medium sm:inline">
            {isExpanded ? m.flow_validation_hide_details() : m.flow_validation_show_details()}
          </span>
          <svg
            class="text-negative-stronger/60 size-4 shrink-0 ease-out motion-safe:transition-transform motion-safe:duration-(--duration-quick) motion-safe:ease-(--ease-smooth-out) {isExpanded
              ? 'rotate-180'
              : ''}"
            aria-hidden="true"
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
          <div
            id="flow-validation-issues"
            class="flex flex-col gap-2 px-4 pb-3"
            transition:slide={{ duration: reducedMotion ? 0 : 200 }}
          >
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
                  {#if issue.detail}
                    <details class="text-muted mt-0.5 text-xs">
                      <summary class="cursor-pointer select-none">
                        {m.flow_validation_technical_details()}
                      </summary>
                      <span class="mt-1 block leading-relaxed break-words">{issue.detail}</span>
                    </details>
                  {/if}
                  {#each issue.repairs ?? [] as repair (`${repair.stepId}:${repair.target.location.kind}:${repair.target.location.kind === "source_ref" ? repair.target.location.index : ""}:${repair.target.token}`)}
                    <div class="mt-2 flex min-w-0 flex-col gap-2">
                      <span class="text-sm font-medium">{repair.stepLabel}</span>
                      <p class="text-secondary text-xs break-words">
                        {m.flow_validation_replace_reference_from({ token: repair.target.token })}
                      </p>
                      {#if repair.options.length > 0}
                        <Select.Root
                          type="single"
                          onValueChange={(value) => {
                            const option = repair.options.find(
                              (candidate) => candidate.key === value
                            );
                            if (option)
                              onRepairReference?.({
                                stepId: repair.stepId,
                                target: repair.target,
                                option
                              });
                          }}
                        >
                          <Select.Trigger
                            class="w-full"
                            aria-label={m.flow_validation_replace_reference()}
                          >
                            {m.flow_validation_replace_reference()}
                          </Select.Trigger>
                          <Select.Content>
                            <Select.Group>
                              {#each repair.options as option (option.key)}
                                <Select.Item value={option.key} label={optionLabel(option)}>
                                  {optionLabel(option)}
                                </Select.Item>
                              {/each}
                            </Select.Group>
                          </Select.Content>
                        </Select.Root>
                      {/if}
                    </div>
                  {/each}
                </div>
                {#if issue.stepId && onNavigateToStep}
                  <button
                    type="button"
                    class="border-accent-default/20 bg-accent-default/5 text-accent-default hover:border-accent-default/40 hover:bg-accent-default/10 shrink-0 rounded-lg border px-3 py-1.5 text-xs font-medium hover:shadow-sm active:scale-[0.98] motion-safe:transition-[background-color,border-color,box-shadow,transform] motion-safe:duration-(--duration-quick)"
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
