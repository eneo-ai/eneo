<script lang="ts">
  import type { Snippet } from "svelte";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import * as ToggleGroup from "$lib/components/ui/toggle-group/index.js";
  import IconArrowRight from "@lucide/svelte/icons/arrow-right";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import { markedView, wordDiff } from "./builderTextDiff";
  import type { StepFieldChange, StepSpec } from "./protocol";
  import type { StepFieldChangeDisplay } from "./BuilderStepDetails.svelte";
  import {
    answerLabel,
    answerPhrase,
    contractFieldCount,
    contractFields,
    fieldDescription,
    fieldLabel,
    inSentence,
    readsLabel as readsLabelFor,
    type ContractField
  } from "./builderStepPhrases";

  /**
   * What one proposed change does to a step, in the reader's words: one
   * sentence, the step's three parts (what it reads, does and answers with),
   * the fields of a new answer and the instruction before and after. The raw
   * values stay reachable behind "tekniska detaljer".
   */
  interface Props {
    step: StepSpec;
    stepNumber: number;
    changes: StepFieldChangeDisplay[];
    stepNumberOf: (planStepRef: string) => number | null;
    /** Renders instruction text with planned-step references made readable. */
    readable: Snippet<[string]>;
  }

  let { step, stepNumber, changes, stepNumberOf, readable }: Props = $props();

  type Part = "reads" | "does" | "answers";
  const FIELD_PART: Partial<Record<StepFieldChange["field"], Part>> = {
    input_source: "reads",
    input_type: "reads",
    input_bindings: "reads",
    input_contract: "reads",
    input_config: "reads",
    knowledge_refs: "reads",
    instructions: "does",
    model_ref: "does",
    output_mode: "does",
    output_type: "answers",
    output_contract: "answers",
    output_config: "answers"
  };
  // Shown by the strip, the sentence and the sections below; everything else
  // is listed as a plain row so no change goes unmentioned. Chosen results
  // and a contract are structures a short reading cannot carry, so they keep
  // a row with their complete before and after behind a fold.
  const TOLD_ELSEWHERE = new Set<StepFieldChange["field"]>([
    "input_source",
    "instructions",
    "model_ref",
    "output_type"
  ]);

  const byField = $derived(new Map(changes.map((change) => [change.field, change])));
  function changed(part: Part): boolean {
    return changes.some((change) => FIELD_PART[change.field] === part);
  }

  const locale = $derived(getLocale());

  function parseContract(detail: string | null | undefined): Record<string, unknown> | null {
    if (!detail) return null;
    try {
      return JSON.parse(detail) as Record<string, unknown>;
    } catch {
      return null;
    }
  }
  const fieldName = (key: string, field: ContractField) => fieldLabel(key, field, locale);

  const currentFields = $derived(contractFields(step.output_contract));
  const previousFields = $derived(
    contractFields(parseContract(byField.get("output_contract")?.previousDetail))
  );
  const removedFields = $derived.by(() => {
    const current = new Set(currentFields.map(([key]) => key));
    return previousFields
      .filter(([key]) => !current.has(key))
      .map(([key, schema]) => fieldName(key, schema));
  });

  // ---- the answer before and after -------------------------------------------
  const currentType = $derived(step.output_type ?? "text");
  const currentCount = $derived(contractFieldCount(step.output_contract));
  const previousType = $derived(byField.get("output_type")?.previousValue ?? currentType);
  const previousCount = $derived(
    byField.has("output_contract") ? previousFields.length : currentCount
  );
  const answerChanged = $derived(byField.has("output_type"));
  const fieldSetChanged = $derived.by(() => {
    if (!byField.has("output_contract")) return false;
    const previous = new Set(previousFields.map(([key]) => key));
    return (
      previous.size !== currentFields.length || currentFields.some(([key]) => !previous.has(key))
    );
  });

  // ---- what the step reads, before and after, with the steps named ------------
  const readsNow = $derived(readsLabelFor(step, stepNumber, stepNumberOf));
  const readsBefore = $derived.by(() => {
    const source = byField.get("input_source");
    const bindings = byField.get("input_bindings");
    if (!source && !bindings) return readsNow;
    let previousBindings: unknown = step.input_bindings;
    if (bindings) {
      try {
        previousBindings = bindings.previousDetail ? JSON.parse(bindings.previousDetail) : null;
      } catch {
        previousBindings = null;
      }
    }
    return readsLabelFor(
      {
        input_source: (source?.previousValue as StepSpec["input_source"]) ?? step.input_source,
        input_bindings: previousBindings as StepSpec["input_bindings"]
      },
      stepNumber,
      stepNumberOf
    );
  });
  const readsChanged = $derived(readsBefore !== readsNow);

  // New fields are named in the sentence, so it reads back like the request.
  const MAX_NAMED_FIELDS = 4;
  const sentence = $derived.by(() => {
    if (currentType === "json" && currentFields.length > 0 && (answerChanged || fieldSetChanged)) {
      const count = String(currentFields.length);
      if (currentFields.length > MAX_NAMED_FIELDS) {
        return m.ai_builder_change_sentence_fields_count({ count });
      }
      const fields = new Intl.ListFormat(locale, { type: "conjunction" }).format(
        currentFields.map(([key, schema]) => inSentence(fieldName(key, schema), locale))
      );
      return currentFields.length === 1
        ? m.ai_builder_change_sentence_fields_named_one({ fields })
        : m.ai_builder_change_sentence_fields_named({ count, fields });
    }
    if (answerChanged) {
      return m.ai_builder_change_sentence_answer({
        current: answerPhrase(currentType, currentCount),
        previous: answerPhrase(previousType, previousCount)
      });
    }
    if (byField.has("output_contract")) return m.ai_builder_change_sentence_fields();
    if (readsChanged) {
      return m.ai_builder_change_sentence_reads({
        current: inSentence(readsNow, locale),
        previous: inSentence(readsBefore, locale)
      });
    }
    if (changed("reads")) return m.ai_builder_change_sentence_reads_other();
    if (byField.has("instructions")) return m.ai_builder_change_sentence_instruction();
    if (byField.has("model_ref")) return m.ai_builder_change_sentence_model();
    const rename = byField.get("name");
    if (rename) return m.ai_builder_change_sentence_name({ name: rename.current });
    if (byField.has("review_policy")) return m.ai_builder_change_sentence_review();
    return m.ai_builder_change_sentence_other();
  });

  const parts = $derived([
    {
      key: "reads",
      label: m.ai_builder_change_part_reads(),
      changes: changed("reads"),
      before: readsChanged ? readsBefore : null,
      value: readsNow
    },
    {
      key: "does",
      label: m.ai_builder_change_part_does(),
      changes: changed("does"),
      before: null,
      value: byField.has("instructions")
        ? m.ai_builder_change_does_instruction()
        : byField.has("model_ref")
          ? m.ai_builder_change_does_model()
          : m.ai_builder_change_does_same()
    },
    {
      key: "answers",
      label: m.ai_builder_change_part_answers(),
      changes: changed("answers"),
      before: answerChanged || fieldSetChanged ? answerLabel(previousType, previousCount) : null,
      value: answerLabel(currentType, currentCount)
    }
  ]);

  const instructionChange = $derived(byField.get("instructions") ?? null);
  const contractChange = $derived(byField.get("output_contract") ?? null);
  const showFields = $derived(changed("answers") && currentFields.length > 0);
  // The field list carries the contract's fold when it is shown.
  const otherRows = $derived(
    changes.filter(
      (change) =>
        !TOLD_ELSEWHERE.has(change.field) && !(change.field === "output_contract" && showFields)
    )
  );

  let instructionOpen = $state(false);
  // The instruction's change as a review tool shows it: one text, removed words
  // struck through, added words marked. Very long texts get the two columns.
  const instructionDiff = $derived(
    instructionChange ? wordDiff(instructionChange.previous, instructionChange.current) : null
  );
  // A light edit reads best marked in one text; a rewrite reads best side by
  // side, as a review tool splits it. The reader can switch either way.
  const rewrittenShare = $derived.by(() => {
    if (!instructionDiff) return 0;
    const total = instructionDiff.reduce((sum, part) => sum + part.text.length, 0);
    const changed = instructionDiff
      .filter((part) => part.kind !== "same")
      .reduce((sum, part) => sum + part.text.length, 0);
    return total > 0 ? changed / total : 0;
  });
  const markedParts = $derived(instructionDiff ? markedView(instructionDiff) : []);
  let chosenDiffView = $state<"marked" | "split" | null>(null);
  const diffView = $derived(chosenDiffView ?? (rewrittenShare > 0.5 ? "split" : "marked"));
  // Ink on a soft tint: removed text keeps a hairline strike, added text a
  // thin underline, so neither leans on colour alone.
  const REMOVED =
    "bg-negative-dimmer text-primary decoration-negative-default rounded-[3px] px-0.5 line-through decoration-1 box-decoration-clone";
  const ADDED =
    "bg-positive-dimmer text-primary decoration-positive-default rounded-[3px] px-0.5 underline decoration-1 underline-offset-[3px] box-decoration-clone";
  // Raw before-and-after values are technical detail: Avancerad shows them,
  // Enkel keeps to the readable summary. Outside the flows layout there is no
  // mode and they show, as before.
  const flowUserMode = getFlowUserMode();
  const showTechnical = $derived(flowUserMode === undefined || $flowUserMode === "power_user");
  let technicalOpen = $state<Record<string, boolean>>({});

  function prettyDetail(detail: string): string {
    try {
      return JSON.stringify(JSON.parse(detail), null, 2);
    } catch {
      return detail;
    }
  }
</script>

{#snippet technical(change: StepFieldChangeDisplay)}
  {#if showTechnical && (change.previousDetail || change.currentDetail)}
    <Collapsible.Root
      open={technicalOpen[change.field] ?? false}
      onOpenChange={(open) => (technicalOpen[change.field] = open)}
    >
      <Collapsible.Trigger
        class="text-accent-stronger focus-visible:ring-accent-stronger mt-1.5 rounded-sm text-xs font-medium underline underline-offset-2 focus-visible:ring-2 focus-visible:outline-none"
      >
        {technicalOpen[change.field]
          ? m.ai_builder_change_hide_technical()
          : m.ai_builder_change_show_technical()}
      </Collapsible.Trigger>
      <Collapsible.Content class="collapsible-animate">
        <div class="mt-2 grid gap-3 sm:grid-cols-2" data-testid="step-field-change-detail">
          {#each [{ label: m.ai_builder_change_before(), value: change.previousDetail, tone: "text-secondary" }, { label: m.ai_builder_change_after(), value: change.currentDetail, tone: "text-primary" }] as side (side.label)}
            <div>
              <div class="text-secondary mb-1 text-xs font-bold">{side.label}</div>
              <pre
                class="bg-secondary {side.tone} m-0 max-h-64 overflow-auto rounded-md p-2 font-mono text-xs leading-snug break-all whitespace-pre-wrap">{side.value
                  ? prettyDetail(side.value)
                  : m.ai_builder_step_change_none()}</pre>
            </div>
          {/each}
        </div>
      </Collapsible.Content>
    </Collapsible.Root>
  {/if}
{/snippet}

<section class="flex max-w-[60rem] flex-col gap-6" data-testid="step-field-changes">
  <Collapsible.Root bind:open={instructionOpen} class="flex flex-col gap-4">
    <p class="text-primary text-[1.0625rem] leading-snug font-bold tracking-[-0.015em] text-pretty">
      {sentence}
    </p>

    <!-- The step's three parts, so the reader sees where the change lands.
         Unchanged parts stay in grey; a change carries a dot and its word. -->
    <ol
      class="m-0 grid list-none gap-x-5 gap-y-3 p-0 sm:grid-cols-[1fr_auto_1fr_auto_1fr]"
      aria-label={m.ai_builder_step_label({ step: stepNumber })}
    >
      {#each parts as part, index (part.key)}
        {#if index > 0}
          <li class="text-secondary hidden pt-5 sm:block" aria-hidden="true">
            <IconArrowRight class="size-4" />
          </li>
        {/if}
        <li class="flex min-w-0 flex-col items-start gap-0.5">
          <span class="text-secondary text-xs font-medium">{part.label}</span>
          <span
            class="text-[0.8125rem] leading-snug text-pretty {part.changes
              ? 'text-primary font-semibold'
              : 'text-secondary'}"
          >
            {#if part.before}
              <span class="sr-only">{m.ai_builder_step_change_previous_label()}: </span>
              <span class="text-secondary font-normal">{part.before}</span>
              <IconArrowRight class="text-secondary mx-0.5 inline size-3.5" aria-hidden="true" />
              <span class="sr-only">{m.ai_builder_step_change_current_label()}: </span>
            {/if}
            {part.value}
          </span>
          <span
            class="mt-0.5 inline-flex items-center gap-1.5 text-xs {part.changes
              ? 'text-accent-stronger font-semibold'
              : 'text-secondary'}"
          >
            {#if part.changes}
              <span class="bg-accent-default size-1.5 rounded-full" aria-hidden="true"></span>
            {/if}
            {part.changes ? m.ai_builder_change_tag_changes() : m.ai_builder_change_tag_unchanged()}
          </span>
          {#if part.key === "does" && instructionChange}
            <Collapsible.Trigger
              class="text-accent-stronger focus-visible:ring-accent-stronger mt-1 rounded-sm text-xs font-medium underline underline-offset-2 focus-visible:ring-2 focus-visible:outline-none"
            >
              {instructionOpen
                ? m.ai_builder_change_hide_before_after()
                : m.ai_builder_change_show_before_after()}
            </Collapsible.Trigger>
          {/if}
        </li>
      {/each}
    </ol>

    {#if instructionChange && instructionDiff}
      <Collapsible.Content class="collapsible-animate">
        <div
          class="border-default overflow-hidden rounded-lg border"
          data-testid="instruction-diff"
        >
          <div
            class="border-default bg-secondary/60 flex flex-wrap items-center gap-x-4 gap-y-2 border-b px-4 py-2"
          >
            <span class="text-primary text-xs font-semibold"
              >{m.ai_builder_step_instructions()}</span
            >
            <!-- The key is for the eye; each change names itself to a screen reader. -->
            <span class="flex items-center gap-2 text-xs" aria-hidden="true">
              <del class={REMOVED}>{m.ai_builder_change_diff_removed()}</del>
              <ins class={ADDED}>{m.ai_builder_change_diff_added()}</ins>
            </span>
            <ToggleGroup.Root
              type="single"
              variant="outline"
              size="sm"
              spacing={0}
              class="ml-auto"
              bind:value={
                () => diffView,
                (value) => {
                  // Clicking the chosen view again would clear it; one is always shown.
                  if (value) chosenDiffView = value as "marked" | "split";
                }
              }
              aria-label={m.ai_builder_change_diff_view_label()}
            >
              <ToggleGroup.Item value="marked" class="px-2.5 text-xs">
                {m.ai_builder_change_diff_marked()}
              </ToggleGroup.Item>
              <ToggleGroup.Item value="split" class="px-2.5 text-xs">
                {m.ai_builder_change_diff_split()}
              </ToggleGroup.Item>
            </ToggleGroup.Root>
          </div>
          {#if diffView === "marked"}
            <p
              class="bg-primary text-primary m-0 px-4 py-3.5 text-[0.8125rem] leading-[1.8] break-words whitespace-pre-wrap"
            >
              {#each markedParts as part, index (index)}
                <!-- Whitespace at a change's edge, and the line breaks inside a
                     removed run, belong to their side unmarked: struck through
                     they would draw a mark over an empty line and announce a
                     second removal for the gap between two struck phrases. -->
                {#if part.kind === "same" || part.plain}
                  {@render readable(part.text)}
                {:else if part.kind === "removed"}
                  <del class={REMOVED}
                    ><span class="sr-only"
                      >{m.ai_builder_change_diff_removed()}:
                    </span>{#if part.marker}<span aria-hidden="true">{part.text}</span><span
                        class="sr-only"
                        >{part.marker === "break"
                          ? m.ai_builder_change_diff_break()
                          : m.ai_builder_change_diff_space()}</span
                      >{:else}{@render readable(part.text)}{/if}</del
                  >
                {:else}
                  <ins class="{ADDED} [del+&]:ms-1"
                    ><span class="sr-only"
                      >{m.ai_builder_change_diff_added()}:
                    </span>{#if part.marker}<span aria-hidden="true">{part.text}</span><span
                        class="sr-only"
                        >{part.marker === "break"
                          ? m.ai_builder_change_diff_break()
                          : m.ai_builder_change_diff_space()}</span
                      >{:else}{@render readable(part.text)}{/if}</ins
                  >
                {/if}
              {/each}
            </p>
          {:else}
            <div
              class="bg-primary divide-default grid divide-y lg:grid-cols-2 lg:divide-x lg:divide-y-0"
            >
              {#each [{ kind: "removed", label: m.ai_builder_change_before() }, { kind: "added", label: m.ai_builder_change_after() }] as column (column.kind)}
                <div class="min-w-0 px-4 py-3.5">
                  <div class="text-secondary mb-1.5 text-xs font-semibold">{column.label}</div>
                  <p
                    class="text-primary m-0 max-w-[72ch] text-[0.8125rem] leading-[1.8] break-words whitespace-pre-wrap"
                  >
                    {#each instructionDiff as part, index (index)}
                      {#if part.kind === "same" || (part.plain && part.kind === column.kind)}
                        {@render readable(part.text)}
                      {:else if part.kind === column.kind}
                        {#if part.kind === "removed"}
                          <del class={REMOVED}
                            ><span class="sr-only"
                              >{m.ai_builder_change_diff_removed()}:
                            </span>{@render readable(part.text)}</del
                          >
                        {:else}
                          <ins class={ADDED}
                            ><span class="sr-only"
                              >{m.ai_builder_change_diff_added()}:
                            </span>{@render readable(part.text)}</ins
                          >
                        {/if}
                      {/if}
                    {/each}
                  </p>
                </div>
              {/each}
            </div>
          {/if}
        </div>
      </Collapsible.Content>
    {:else if instructionChange}
      <Collapsible.Content class="collapsible-animate">
        <div class="bg-secondary grid gap-x-8 gap-y-4 rounded-lg px-4 py-3.5 lg:grid-cols-2">
          <div>
            <div class="text-secondary mb-1 text-xs font-bold">{m.ai_builder_change_before()}</div>
            <blockquote
              class="text-secondary m-0 text-[0.8125rem] leading-relaxed break-words whitespace-pre-wrap"
              aria-label={m.ai_builder_step_change_previous_instructions_label()}
            >
              {#if instructionChange.previous}
                {@render readable(instructionChange.previous)}
              {:else}
                {m.ai_builder_step_change_none()}
              {/if}
            </blockquote>
          </div>
          <div>
            <div class="text-secondary mb-1 text-xs font-bold">{m.ai_builder_change_after()}</div>
            <p
              class="text-primary m-0 text-[0.8125rem] leading-relaxed break-words whitespace-pre-wrap"
            >
              {@render readable(instructionChange.current)}
            </p>
          </div>
        </div>
      </Collapsible.Content>
    {/if}
  </Collapsible.Root>

  {#if showFields}
    <div>
      <h4 class="text-primary mb-1 text-[0.8125rem] font-bold">
        {m.ai_builder_change_fields_title()}
      </h4>
      <dl class="divide-dimmer m-0 flex flex-col divide-y">
        {#each currentFields as [key, schema] (key)}
          {@const name = fieldName(key, schema)}
          {@const description = fieldDescription(name, schema, locale)}
          <div class="grid gap-x-6 gap-y-0.5 py-2.5 sm:grid-cols-[minmax(10rem,16rem)_1fr]">
            <dt class="text-primary text-[0.8125rem] font-semibold">{name}</dt>
            <dd class="text-secondary m-0 text-[0.8125rem] leading-relaxed">
              {description ?? ""}
            </dd>
          </div>
        {/each}
      </dl>
      {#if removedFields.length > 0}
        <p class="text-secondary mt-1 text-[0.8125rem]">
          {m.ai_builder_change_fields_removed({ fields: removedFields.join(", ") })}
        </p>
      {/if}
      {#if contractChange}
        {@render technical(contractChange)}
      {/if}
    </div>
  {/if}

  {#if otherRows.length > 0}
    <dl class="m-0 flex flex-col gap-2 text-[0.8125rem]">
      {#each otherRows as change (change.field)}
        <div class="grid gap-x-6 gap-y-0.5 sm:grid-cols-[minmax(10rem,16rem)_1fr]">
          <dt class="text-primary font-semibold">{change.label}</dt>
          <dd class="m-0 min-w-0 break-words">
            {#if change.previous === change.current}
              <span class="text-primary">{m.ai_builder_step_change_changed()}</span>
            {:else}
              <span class="sr-only">{m.ai_builder_step_change_previous_label()}: </span>
              <span class="text-secondary">{change.previous}</span>
              <IconArrowRight class="text-secondary mx-0.5 inline size-3.5" aria-hidden="true" />
              <span class="sr-only">{m.ai_builder_step_change_current_label()}: </span>
              <span class="text-primary font-semibold">{change.current}</span>
            {/if}
            {@render technical(change)}
          </dd>
        </div>
      {/each}
    </dl>
  {/if}
</section>
