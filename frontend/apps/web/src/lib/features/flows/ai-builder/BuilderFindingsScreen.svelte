<script lang="ts">
  import { BUILDER_COLUMN } from "./builderColumns";
  import { tick, type Snippet } from "svelte";
  import { SvelteSet } from "svelte/reactivity";
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import { Checkbox } from "$lib/components/ui/checkbox/index.js";
  import IconArrowLeft from "@lucide/svelte/icons/arrow-left";
  import IconLightbulb from "@lucide/svelte/icons/lightbulb";
  import IconCheck from "@lucide/svelte/icons/check";
  import IconInfo from "@lucide/svelte/icons/info";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import type {
    AIBuilderFlowReviewFact,
    AIBuilderFlowReviewState,
    AIBuilderFlowReviewSuggestion,
    AIBuilderFlowReviewSuggestionsState,
    AIBuilderReviewReference
  } from "./protocol";
  import {
    MAX_FINDINGS_PER_CHANGE,
    describeReviewFact,
    dismissedFindingIds,
    rememberDismissedFinding
  } from "./flowReviewFindings";
  import {
    canonicalFoci,
    investigationMessage,
    suggestionKindLabel,
    suggestionSourceLabel,
    suggestionStepsLabel,
    suggestionsFailureCopy
  } from "./flowReviewSuggestions";

  interface Props {
    review: AIBuilderFlowReviewState;
    suggestions?: AIBuilderFlowReviewSuggestionsState;
    disabled?: boolean;
    /** The composer's model and effort controls, rendered beside the
     *  suggest action so the same selection judges the sample. */
    plannerControls?: Snippet;
    onprepare: (detail: { message: string; reviewContext: AIBuilderReviewReference }) => void;
    onsuggest?: () => void;
    onclose: () => void;
    onretry: () => void;
  }

  let {
    review,
    suggestions = { status: "closed" },
    disabled = false,
    plannerControls,
    onprepare,
    onsuggest,
    onclose,
    onretry
  }: Props = $props();

  let dismissed = $state<Set<string>>(new Set());
  /** Which suggestion cards show their quotes; folded by default so the
   *  finding, not its evidence, is what the reviewer reads first. */
  let openSources = $state<Record<number, boolean>>({});
  let sendsOpen = $state(false);
  $effect(() => {
    if (review.status === "ready") {
      dismissed = dismissedFindingIds(review.packet.flow_id);
    }
  });

  const packet = $derived(review.status === "ready" ? review.packet : null);
  const completeness = $derived(
    packet?.facts.find((fact) => fact.kind === "evidence_completeness") ?? null
  );
  const findings = $derived(
    (packet?.facts ?? []).filter(
      (fact) => fact.kind !== "evidence_completeness" && !dismissed.has(fact.finding_id)
    )
  );
  const hiddenCount = $derived(
    (packet?.facts ?? []).filter(
      (fact) => fact.kind !== "evidence_completeness" && dismissed.has(fact.finding_id)
    ).length
  );
  const runCount = $derived(
    packet ? packet.cohort.completed_run_ids.length + packet.cohort.failed_run_ids.length : 0
  );
  const omittedCount = $derived(
    packet
      ? (packet.cohort.omitted.not_viewable ?? 0) +
          (packet.cohort.omitted.level_unknown ?? 0) +
          (packet.cohort.omitted.overflow ?? 0)
      : 0
  );

  /* Both halves are read first and acted on once: you tick what is worth
     changing, then send the whole tick list as one turn. Both server
     contracts already take a set (`finding_ids`, `suggestions`), so a
     selection costs no extra round trip. The two halves stay separate
     selections because they are separate requests: one is grounded in what
     was counted, the other in what a model read. */
  const pickedFindings = new SvelteSet<string>();
  const pickedSuggestions = new SvelteSet<number>();

  const selectedFindings = $derived(findings.filter((f) => pickedFindings.has(f.finding_id)));
  /* One change request carries at most MAX_FINDINGS_PER_CHANGE findings; the
     server rejects more. Stop the selection at the bound rather than letting
     someone tick fifteen and meet a validation error they cannot act on. */
  const findingsAtLimit = $derived(selectedFindings.length >= MAX_FINDINGS_PER_CHANGE);

  function toggle<T>(set: SvelteSet<T>, key: T, on: boolean) {
    if (on) set.add(key);
    else set.delete(key);
  }

  /* A finding hidden while ticked would otherwise keep voting from off
     screen. Same for a suggestion list replaced by a new judgement. */
  $effect(() => {
    const live = new Set(findings.map((f) => f.finding_id));
    for (const id of pickedFindings) if (!live.has(id)) pickedFindings.delete(id);
  });
  $effect(() => {
    const count = suggestions.status === "ready" ? suggestions.suggestions.suggestions.length : 0;
    for (const index of pickedSuggestions) if (index >= count) pickedSuggestions.delete(index);
  });

  function prepare(facts: AIBuilderFlowReviewFact[]) {
    if (!packet || facts.length === 0) return;
    const described = facts.map((fact) => describeReviewFact(fact, packet.steps).title);
    onprepare({
      message: m.ai_builder_review_prepare_message({ finding: described.join("; ") }),
      reviewContext: {
        kind: "flow_review",
        flow_version: packet.flow_version,
        definition_checksum: packet.definition_checksum,
        finding_ids: facts.map((fact) => fact.finding_id)
      }
    });
  }

  function investigate(selected: AIBuilderFlowReviewSuggestion[]) {
    if (!packet || suggestions.status !== "ready" || selected.length === 0) return;
    // One turn however many were selected. The set is canonical before the
    // sentence and the payload are built from it, so they agree with what
    // the server retains; the rationale and quotes never travel.
    const foci = canonicalFoci(selected);
    onprepare({
      message: investigationMessage(foci),
      reviewContext: {
        kind: "flow_review_suggestion",
        flow_version: suggestions.suggestions.flow_version,
        definition_checksum: suggestions.suggestions.definition_checksum,
        sample_run_ids: suggestions.suggestions.sample.run_ids,
        suggestions: foci
      }
    });
  }

  let hiddenNotice = $state("");

  async function dismiss(fact: AIBuilderFlowReviewFact) {
    if (!packet) return;
    const remaining = findings.filter((f) => f.finding_id !== fact.finding_id);
    const nextId = remaining[findings.indexOf(fact)]?.finding_id ?? remaining.at(-1)?.finding_id;

    rememberDismissedFinding(packet.flow_id, fact.finding_id);
    pickedFindings.delete(fact.finding_id);
    dismissed = new Set([...dismissed, fact.finding_id]);
    // `hiddenCount` is derived from `dismissed`, which was just assigned, so
    // it already counts this one. Adding another announced one more hidden
    // item than the restore button offered.
    hiddenNotice =
      hiddenCount === 1
        ? m.ai_builder_review_hidden_notice()
        : m.ai_builder_review_hidden_notice_count({ count: String(hiddenCount) });

    await tick();
    const next = nextId
      ? document.querySelector<HTMLElement>(`[data-finding-id="${nextId}"] h4`)
      : document.querySelector<HTMLElement>('[data-testid="builder-findings"] h3');
    next?.focus();
  }

  function showHidden() {
    if (!packet) return;
    dismissed = new Set();
    rememberDismissedFinding(packet.flow_id, null);
  }
</script>

<div class="flex flex-1 justify-center px-7 pt-7 pb-8 max-sm:px-3 max-sm:pt-4 max-sm:pb-5">
  <div class="findings-screen w-full {BUILDER_COLUMN.sheet}">
    <section
      class="border-stronger bg-primary overflow-hidden rounded-xl border shadow-xs"
      aria-label={m.ai_builder_review_title()}
      data-testid="builder-findings"
    >
      <header
        class="bg-accent-dimmer border-accent-default/25 flex items-start justify-between gap-3 border-b px-5 py-3.5"
      >
        <div class="min-w-0">
          <h2
            class="text-primary text-[1.0625rem] font-bold tracking-[-0.015em]"
            tabindex="-1"
            data-builder-screen-heading
          >
            {m.ai_builder_review_title()}
          </h2>
          {#if packet || review.status === "loading"}
            <p class="text-accent-stronger mt-1 text-[0.8125rem] text-pretty">
              {#if packet}
                {runCount === 1
                  ? m.ai_builder_review_lead_one({ version: String(packet.flow_version) })
                  : m.ai_builder_review_lead({
                      version: String(packet.flow_version),
                      total: String(runCount)
                    })}{packet.cohort.failed_run_ids.length > 0
                  ? m.ai_builder_review_lead_failed({
                      failed: String(packet.cohort.failed_run_ids.length)
                    })
                  : ""}
              {:else}
                {m.ai_builder_review_lead_loading()}
              {/if}
            </p>
          {/if}
        </div>
        <Button variant="outline" size="sm" class="ml-auto shrink-0 gap-1.5" onclick={onclose}>
          <IconArrowLeft class="size-3.5" aria-hidden="true" />
          {m.ai_builder_review_back()}
        </Button>
      </header>

      <div class="px-5 pt-[1.125rem] pb-5">
        {#if review.status === "loading"}
          <div class="flex flex-col gap-3" aria-busy="true">
            <Skeleton class="h-[4.5rem] w-full rounded-lg" />
            <Skeleton class="h-[4.5rem] w-full rounded-lg" />
          </div>
        {:else if review.status === "failed"}
          <div
            class="bg-warning-dimmer border-warning-default/45 text-warning-stronger rounded-[9px] border px-3 py-2.5 text-[0.8125rem]"
            role="status"
          >
            <p class="font-semibold">
              {review.error.code === "flow_not_published"
                ? m.ai_builder_review_unpublished_title()
                : review.error.code === "review_flow_too_large"
                  ? m.ai_builder_review_flow_too_large_title()
                  : m.ai_builder_review_load_failed()}
            </p>
            <p class="mt-0.5">
              {review.error.code === "flow_not_published"
                ? m.ai_builder_review_unpublished_body()
                : review.error.code === "review_flow_too_large"
                  ? m.ai_builder_review_flow_too_large()
                  : review.error.message}
            </p>
            {#if review.error.code !== "flow_not_published" && review.error.code !== "review_flow_too_large"}
              <Button variant="outline" size="sm" class="mt-2.5" onclick={onretry}>
                {m.ai_builder_review_retry()}
              </Button>
            {/if}
          </div>
        {:else if packet && runCount === 0}
          <p class="text-secondary text-[0.9375rem] text-pretty" data-testid="findings-no-runs">
            {m.ai_builder_review_no_runs()}
          </p>
          {#if omittedCount > 0}
            <p class="text-secondary mt-1.5 text-[0.8125rem]">
              {#if omittedCount === 1}
                {m.ai_builder_review_omitted_one()}
              {:else}
                {m.ai_builder_review_omitted({ count: String(omittedCount) })}
              {/if}
            </p>
          {/if}
        {:else if packet}
          <p class="sr-only" role="status" aria-live="polite">{hiddenNotice}</p>
          <div class="mb-2.5 flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
            <h3
              id="review-facts-title"
              tabindex="-1"
              class="text-primary text-[0.9375rem] font-bold outline-none"
            >
              {m.ai_builder_review_facts_title()}
            </h3>
            {#if findings.length > 1}
              <Button
                variant="link"
                class="text-accent-stronger -my-1 h-auto px-0 py-1 text-[0.8125rem] font-semibold"
                data-testid="findings-select-all"
                {disabled}
                onclick={() => {
                  if (pickedFindings.size > 0) pickedFindings.clear();
                  else
                    for (const fact of findings.slice(0, MAX_FINDINGS_PER_CHANGE))
                      pickedFindings.add(fact.finding_id);
                }}
              >
                {pickedFindings.size > 0
                  ? m.ai_builder_review_select_none()
                  : findings.length > MAX_FINDINGS_PER_CHANGE
                    ? m.ai_builder_review_select_max({
                        max: String(MAX_FINDINGS_PER_CHANGE),
                        total: String(findings.length)
                      })
                    : m.ai_builder_review_select_all({ count: String(findings.length) })}
              </Button>
            {/if}
          </div>
          {#if findings.length === 0}
            <p
              class="text-secondary flex items-center gap-1.5 text-[0.9375rem] text-pretty"
              data-testid="findings-none"
            >
              {#if hiddenCount === 0}
                <IconCheck class="text-positive-stronger size-4 shrink-0" aria-hidden="true" />
              {/if}
              {hiddenCount > 0
                ? m.ai_builder_review_all_hidden()
                : m.ai_builder_review_nothing_found()}
            </p>
          {:else}
            <!-- Rows, not cards: a card inside the panel painted a 1.07:1
                 fill behind a 1.35:1 hairline, a box drawn in colours nobody
                 can see. Space groups these instead: 26px between rows
                 against 2px between a finding and its own evidence line, so
                 proximity says what belongs together. The rule is a second
                 cue at 1.8:1, not the thing carrying the grouping; a stroke
                 heavy enough to carry it alone would rule this like a table. -->
            <ul
              class="flex flex-col"
              aria-labelledby="review-facts-title"
              data-testid="findings-list"
            >
              {#each findings as fact (fact.finding_id)}
                {@const described = describeReviewFact(fact, packet.steps)}
                {@const picked = pickedFindings.has(fact.finding_id)}
                <li
                  class="border-stronger flex items-start gap-3 border-t py-3.5 first:border-t-0 first:pt-0"
                  data-finding-id={fact.finding_id}
                >
                  <Checkbox
                    class="mt-1 shrink-0"
                    checked={picked}
                    disabled={disabled || (findingsAtLimit && !picked)}
                    aria-label={described.title}
                    aria-describedby={findingsAtLimit && !picked ? "review-facts-limit" : undefined}
                    onCheckedChange={(on) => toggle(pickedFindings, fact.finding_id, on === true)}
                  />
                  <div class="min-w-0 flex-1">
                    <h4
                      tabindex="-1"
                      class="text-primary text-[0.9375rem] font-semibold outline-none first-letter:uppercase"
                    >
                      {described.title}
                    </h4>
                    <p class="text-secondary mt-0.5 text-[0.8125rem] text-pretty">
                      {described.evidence}
                    </p>
                  </div>
                  <Button
                    variant="ghost"
                    size="sm"
                    class="text-secondary h-7 shrink-0 px-2 text-xs"
                    {disabled}
                    onclick={() => dismiss(fact)}
                  >
                    {m.ai_builder_review_hide()}
                  </Button>
                </li>
              {/each}
            </ul>
            <!-- This does open a turn with the planner: the callback sends
                 the message and the finding ids straight to `sendMessage`.
                 What travels is the findings you ticked, named by step and
                 count, and not the run excerpts the suggestions path sends,
                 which is why this line is shorter than that one rather than
                 absent. One grey line in either state. -->
            {#if selectedFindings.length > 0}
              <div class="selection-bar mt-3.5 flex flex-wrap items-center gap-x-3 gap-y-1.5">
                <Button
                  variant="outline"
                  size="sm"
                  class="h-8"
                  {disabled}
                  data-testid="prepare-selected"
                  onclick={() => prepare(selectedFindings)}
                >
                  {selectedFindings.length === 1
                    ? m.ai_builder_review_prepare()
                    : m.ai_builder_review_prepare_count({
                        count: String(selectedFindings.length)
                      })}
                </Button>
                <span class="text-secondary text-[0.8125rem]">
                  {m.ai_builder_review_prepare_hint()}
                </span>
                {#if findingsAtLimit && findings.length > MAX_FINDINGS_PER_CHANGE}
                  <p
                    id="review-facts-limit"
                    class="text-secondary basis-full text-[0.8125rem] text-pretty"
                    role="status"
                  >
                    {m.ai_builder_review_select_limit_reached({
                      max: String(MAX_FINDINGS_PER_CHANGE)
                    })}
                  </p>
                {/if}
              </div>
            {:else}
              <p class="text-secondary mt-3.5 text-[0.8125rem] text-pretty">
                {m.ai_builder_review_select_hint()}
              </p>
            {/if}
          {/if}

          <section
            class="border-stronger mt-7 border-t pt-5"
            aria-label={m.ai_builder_review_suggestions_title()}
            data-testid="review-suggestions"
          >
            <div class="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
              <h3 id="review-suggestions-title" class="text-primary text-[0.9375rem] font-bold">
                {m.ai_builder_review_suggestions_title()}
              </h3>
              {#if suggestions.status === "ready" && suggestions.suggestions.suggestions.length > 1}
                {@const total = suggestions.suggestions.suggestions.length}
                <Button
                  variant="link"
                  class="text-accent-stronger -my-1 h-auto px-0 py-1 text-[0.8125rem] font-semibold"
                  data-testid="suggestions-select-all"
                  {disabled}
                  onclick={() => {
                    if (pickedSuggestions.size === total) pickedSuggestions.clear();
                    else for (let i = 0; i < total; i += 1) pickedSuggestions.add(i);
                  }}
                >
                  {pickedSuggestions.size === total
                    ? m.ai_builder_review_select_none()
                    : m.ai_builder_review_select_all({ count: String(total) })}
                </Button>
              {/if}
            </div>
            {#if suggestions.status === "closed"}
              <div class="mt-2 flex flex-col gap-2">
                <p class="text-secondary text-[0.8125rem] text-pretty">
                  {m.ai_builder_review_suggestions_hint()}
                </p>
                <div class="flex flex-wrap items-center gap-2">
                  <Button
                    variant="outline"
                    size="sm"
                    class="h-8 w-fit gap-1.5"
                    disabled={disabled || runCount === 0}
                    onclick={() => onsuggest?.()}
                  >
                    <IconLightbulb class="size-3.5" aria-hidden="true" />
                    {m.ai_builder_review_suggest()}
                  </Button>
                  {@render plannerControls?.()}
                </div>
              </div>
            {:else if suggestions.status === "loading"}
              <p class="text-secondary text-[0.8125rem]" aria-busy="true" role="status">
                {m.ai_builder_review_suggestions_loading()}
              </p>
              <div class="mt-2.5 flex flex-col gap-2.5">
                <Skeleton class="h-[5rem] w-full rounded-lg" />
                <Skeleton class="h-[5rem] w-full rounded-lg" />
              </div>
            {:else if suggestions.status === "failed"}
              {@const failure = suggestionsFailureCopy(suggestions.error)}
              <div
                class="bg-warning-dimmer border-warning-default/45 text-warning-stronger rounded-[9px] border px-3 py-2.5 text-[0.8125rem]"
                role="status"
              >
                <p class="font-semibold">{failure.title}</p>
                {#if failure.body}
                  <p class="mt-0.5">{failure.body}</p>
                {/if}
                {#if failure.retry}
                  <!-- The controls stay: a model the sample's evidence level
                       refuses is corrected here, then retried. -->
                  <div class="mt-2.5 flex flex-wrap items-center gap-2">
                    <Button variant="outline" size="sm" onclick={() => onsuggest?.()}>
                      {m.ai_builder_review_retry()}
                    </Button>
                    {@render plannerControls?.()}
                  </div>
                {/if}
              </div>
            {:else}
              {@const judged = suggestions.suggestions}
              {@const unread =
                judged.sample.excerpts_omitted_by_budget +
                judged.sample.excerpts_omitted_by_reader +
                judged.sample.excerpts_not_recorded +
                judged.sample.excerpts_unavailable}
              {@const coverage = {
                total: String(
                  judged.sample.excerpts_included + judged.sample.excerpts_truncated + unread
                ),
                truncated: String(judged.sample.excerpts_truncated),
                unread: String(unread)
              }}
              {@const coverageText =
                judged.sample.excerpts_truncated > 0 && unread > 0
                  ? m.ai_builder_review_suggestions_coverage_truncated_unread(coverage)
                  : judged.sample.excerpts_truncated > 0
                    ? m.ai_builder_review_suggestions_coverage_truncated(coverage)
                    : unread > 0
                      ? m.ai_builder_review_suggestions_coverage_unread(coverage)
                      : null}
              {@const readingNote = [
                m.ai_builder_review_suggestions_coverage_model({ model: judged.model_name }),
                coverageText
              ]
                .filter(Boolean)
                .join(" ")}
              <p
                class="text-secondary mt-0.5 flex items-center gap-1 text-[0.8125rem]"
                data-testid="suggestions-lead"
              >
                <!-- "Suggestions, not confirmed faults" used to appear only on
                     the button that asks for them, so it vanished exactly when
                     the guesses arrived. It belongs next to the results. -->
                <span>
                  <span class="text-primary font-semibold"
                    >{m.ai_builder_review_suggestions_advisory()}</span
                  >
                  {judged.sample.run_ids.length === 1
                    ? m.ai_builder_review_suggestions_lead_one()
                    : m.ai_builder_review_suggestions_lead({
                        runs: String(judged.sample.run_ids.length)
                      })}{coverageText ? ` · ${m.ai_builder_review_suggestions_partly_read()}` : ""}
                </span>
                <Tooltip.Provider delayDuration={150}>
                  <Tooltip.Root>
                    <Tooltip.Trigger
                      class="text-secondary hover:text-primary focus-visible:ring-ring -my-0.5 inline-flex size-[24px] items-center justify-center rounded-full focus-visible:ring-2 focus-visible:outline-none"
                      aria-label={readingNote}
                    >
                      <IconInfo class="size-3.5" aria-hidden="true" />
                    </Tooltip.Trigger>
                    <Tooltip.Content class="max-w-[36ch] text-pretty">{readingNote}</Tooltip.Content
                    >
                  </Tooltip.Root>
                </Tooltip.Provider>
              </p>
              {#if judged.suggestions.length === 0 && judged.unverified_count > 0}
                <div
                  class="text-secondary mt-3 text-[0.9375rem] text-pretty"
                  data-testid="suggestions-unverified"
                >
                  <p>
                    {judged.unverified_count === 1
                      ? m.ai_builder_review_suggestions_all_unverified_one()
                      : m.ai_builder_review_suggestions_all_unverified({
                          count: String(judged.unverified_count)
                        })}
                  </p>
                  <Button
                    variant="outline"
                    size="sm"
                    class="mt-2.5"
                    {disabled}
                    onclick={() => onsuggest?.()}
                  >
                    {m.ai_builder_review_retry()}
                  </Button>
                </div>
              {:else if judged.suggestions.length === 0}
                <p
                  class="text-secondary mt-3 text-[0.9375rem] text-pretty"
                  data-testid="suggestions-none"
                >
                  {m.ai_builder_review_suggestions_none()}
                </p>
              {:else}
                <ul
                  class="mt-3 flex flex-col"
                  aria-labelledby="review-suggestions-title"
                  data-testid="suggestions-list"
                >
                  {#each judged.suggestions as suggestion, index (index)}
                    <!-- A suggestion row is deliberately not a finding row:
                         the bulb beside its heading, the same mark as the
                         button that asked for it, says on every row that this
                         is a model's idea and not a measurement. A tinted
                         left gutter said it before; the design keeps colour
                         off borders. -->
                    <li
                      class="border-stronger flex items-start gap-3 border-t py-3.5 first:border-t-0 first:pt-0"
                    >
                      <Checkbox
                        class="mt-1 shrink-0"
                        checked={pickedSuggestions.has(index)}
                        {disabled}
                        aria-label={m.ai_builder_review_suggestion_investigate_this_label({
                          index: String(index + 1),
                          kind: suggestionKindLabel(suggestion.kind),
                          steps: suggestionStepsLabel(suggestion.step_orders)
                        })}
                        onCheckedChange={(on) => toggle(pickedSuggestions, index, on === true)}
                      />
                      <div class="min-w-0 flex-1">
                        <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                          <h4
                            class="text-primary inline-flex items-center gap-1.5 text-[0.9375rem] font-semibold"
                          >
                            <IconLightbulb
                              class="text-secondary size-3.5 shrink-0"
                              aria-hidden="true"
                            />
                            {suggestionKindLabel(suggestion.kind)}
                          </h4>
                          <span class="text-secondary text-[0.8125rem]">
                            {suggestionStepsLabel(suggestion.step_orders)}
                          </span>
                        </div>
                        <p class="text-secondary mt-1 text-[0.8125rem] text-pretty">
                          {suggestion.rationale}
                        </p>
                        <Collapsible.Root
                          open={openSources[index] ?? false}
                          onOpenChange={(open) => (openSources[index] = open)}
                        >
                          <Collapsible.Trigger
                            class="text-secondary hover:text-primary focus-visible:ring-accent-stronger mt-1.5 -mb-1 inline-flex min-h-[24px] items-center rounded-sm text-[0.8125rem] font-semibold underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:outline-none"
                          >
                            {openSources[index]
                              ? m.ai_builder_review_suggestion_sources_hide()
                              : suggestion.sources.length === 1
                                ? m.ai_builder_review_suggestion_sources_show_one()
                                : m.ai_builder_review_suggestion_sources_show({
                                    count: String(suggestion.sources.length)
                                  })}
                          </Collapsible.Trigger>
                          <Collapsible.Content>
                            <ul class="mt-2 flex flex-col gap-1.5">
                              {#each suggestion.sources as source, sourceIndex (sourceIndex)}
                                <li class="text-[0.8125rem]">
                                  <span class="text-secondary">
                                    {suggestionSourceLabel(source, judged.sample.run_ids)}:
                                  </span>
                                  <q class="text-primary">{source.quote}</q>
                                </li>
                              {/each}
                            </ul>
                          </Collapsible.Content>
                        </Collapsible.Root>
                      </div>
                    </li>
                  {/each}
                </ul>
                {#if judged.unverified_count > 0}
                  <p
                    class="text-secondary mt-2 text-[0.8125rem] text-pretty"
                    data-testid="suggestions-some-unverified"
                  >
                    {judged.unverified_count === 1
                      ? m.ai_builder_review_suggestions_some_unverified_one()
                      : m.ai_builder_review_suggestions_some_unverified({
                          count: String(judged.unverified_count)
                        })}
                  </p>
                {/if}
                <!-- The action sits after the list and counts what is ticked:
                     asking someone to investigate all of them before they have
                     read one is asking for a decision they cannot make yet. -->
                {@const picked = judged.suggestions.filter((_, i) => pickedSuggestions.has(i))}
                <!-- Above the action, not below it: this is the half that
                     sends run excerpts to a model, so the question has to be
                     answerable before the click rather than after it. Four
                     facts left open are a grey wall under the list; behind
                     their own question they are one line that says a
                     disclosure exists and where it is. -->
                <Collapsible.Root bind:open={sendsOpen}>
                  <Collapsible.Trigger
                    class="text-secondary hover:text-primary focus-visible:ring-accent-stronger mt-3 inline-flex min-h-[24px] items-center rounded-sm text-[0.8125rem] font-semibold underline-offset-2 hover:underline focus-visible:ring-2 focus-visible:outline-none"
                    data-testid="suggestions-sends"
                  >
                    {m.ai_builder_review_sends_question()}
                  </Collapsible.Trigger>
                  <Collapsible.Content>
                    <p class="text-secondary mt-1 text-[0.8125rem] text-pretty">
                      {picked.length === 1
                        ? m.ai_builder_review_suggestion_investigate_hint()
                        : m.ai_builder_review_suggestion_investigate_all_hint()}
                    </p>
                  </Collapsible.Content>
                </Collapsible.Root>
                {#if picked.length > 0}
                  <div class="selection-bar mt-2.5">
                    <Button
                      variant="outline"
                      size="sm"
                      class="h-8"
                      {disabled}
                      data-testid="investigate-selected"
                      onclick={() => investigate(picked)}
                    >
                      {picked.length === 1
                        ? m.ai_builder_review_suggestion_investigate()
                        : m.ai_builder_review_suggestion_investigate_count({
                            count: String(picked.length)
                          })}
                    </Button>
                  </div>
                {:else}
                  <p class="text-secondary mt-2.5 text-[0.8125rem] text-pretty">
                    {m.ai_builder_review_select_hint_suggestions()}
                  </p>
                {/if}
              {/if}
            {/if}
          </section>

          {@const incompleteCount =
            completeness && completeness.kind === "evidence_completeness"
              ? completeness.runs_missing_step_results
              : 0}
          {@const usageWithheldCount =
            completeness && completeness.kind === "evidence_completeness"
              ? (completeness.runs_with_usage_withheld ?? 0)
              : 0}
          {#if incompleteCount > 0 || usageWithheldCount > 0 || omittedCount > 0 || hiddenCount > 0}
            <footer class="border-default mt-4 border-t pt-3 text-[0.8125rem]">
              <p class="text-secondary text-pretty">
                {#if incompleteCount === 1}
                  {m.ai_builder_review_completeness_one()}
                {:else if incompleteCount > 1}
                  {m.ai_builder_review_completeness({ incomplete: String(incompleteCount) })}
                {/if}
                {#if usageWithheldCount === 1}
                  {m.ai_builder_review_usage_withheld_one()}
                {:else if usageWithheldCount > 1}
                  {m.ai_builder_review_usage_withheld({ count: String(usageWithheldCount) })}
                {/if}
                {#if omittedCount === 1}
                  {m.ai_builder_review_omitted_one()}
                {:else if omittedCount > 1}
                  {m.ai_builder_review_omitted({ count: String(omittedCount) })}
                {/if}
              </p>
              {#if hiddenCount > 0}
                <Button
                  variant="link"
                  class="text-accent-stronger mt-1 -mb-1 h-auto px-0 py-1 text-xs font-semibold"
                  {disabled}
                  onclick={showHidden}
                >
                  {hiddenCount === 1
                    ? m.ai_builder_review_show_hidden_one()
                    : m.ai_builder_review_show_hidden({ count: String(hiddenCount) })}
                </Button>
              {/if}
            </footer>
          {/if}
        {/if}
      </div>
    </section>
  </div>
</div>

<style>
  .findings-screen {
    animation: builder-screen-in var(--duration-fast) var(--ease-smooth-out);
  }
  /* The bar appears the moment the first row is ticked; it should arrive,
     not blink. Quick, because it answers a click the reader just made. */
  .selection-bar {
    animation: selection-bar-in var(--duration-quick) var(--ease-smooth-out);
  }
  @keyframes selection-bar-in {
    from {
      opacity: 0;
      transform: translateY(var(--distance-micro, 4px));
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .findings-screen,
    .selection-bar {
      animation: none;
    }
  }
</style>
