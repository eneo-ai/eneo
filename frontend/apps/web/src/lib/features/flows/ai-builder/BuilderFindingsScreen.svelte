<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Skeleton } from "$lib/components/ui/skeleton/index.js";
  import IconX from "@lucide/svelte/icons/x";
  import IconArrowLeft from "@lucide/svelte/icons/arrow-left";
  import IconSparkles from "@lucide/svelte/icons/sparkles";
  import type {
    AIBuilderFlowReviewFact,
    AIBuilderFlowReviewState,
    AIBuilderFlowReviewSuggestion,
    AIBuilderFlowReviewSuggestionsState,
    AIBuilderReviewReference
  } from "./protocol";
  import {
    describeReviewFact,
    dismissedFindingIds,
    rememberDismissedFinding
  } from "./flowReviewFindings";
  import {
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
    onprepare: (detail: { message: string; reviewContext: AIBuilderReviewReference }) => void;
    onsuggest?: () => void;
    onclose: () => void;
    onretry: () => void;
  }

  let {
    review,
    suggestions = { status: "closed" },
    disabled = false,
    onprepare,
    onsuggest,
    onclose,
    onretry
  }: Props = $props();

  let dismissed = $state<Set<string>>(new Set());
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

  function prepare(fact: AIBuilderFlowReviewFact) {
    if (!packet) return;
    const described = describeReviewFact(fact, packet.steps);
    onprepare({
      message: m.ai_builder_review_prepare_message({ finding: described.title }),
      reviewContext: {
        kind: "flow_review",
        flow_version: packet.flow_version,
        definition_checksum: packet.definition_checksum,
        finding_ids: [fact.finding_id]
      }
    });
  }

  function investigate(suggestion: AIBuilderFlowReviewSuggestion) {
    if (!packet || suggestions.status !== "ready") return;
    // Fixed text from kind and steps; the server writes the same text itself
    // and never sees the rationale or the quotes.
    onprepare({
      message: investigationMessage(suggestion),
      reviewContext: {
        kind: "flow_review_suggestion",
        flow_version: suggestions.suggestions.flow_version,
        definition_checksum: suggestions.suggestions.definition_checksum,
        sample_run_ids: suggestions.suggestions.sample.run_ids,
        suggestion_kind: suggestion.kind,
        step_orders: suggestion.step_orders
      }
    });
  }

  function dismiss(fact: AIBuilderFlowReviewFact) {
    if (!packet) return;
    rememberDismissedFinding(packet.flow_id, fact.finding_id);
    dismissed = new Set([...dismissed, fact.finding_id]);
  }

  function showHidden() {
    if (!packet) return;
    dismissed = new Set();
    rememberDismissedFinding(packet.flow_id, null);
  }
</script>

<div class="flex flex-1 justify-center px-7 pt-7 pb-8 max-sm:px-3 max-sm:pt-4 max-sm:pb-5">
  <div class="findings-screen w-full max-w-[43.75rem] 2xl:max-w-[48.125rem]">
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
                {m.ai_builder_review_lead({
                  version: String(packet.flow_version),
                  completed: String(packet.cohort.completed_run_ids.length),
                  failed: String(packet.cohort.failed_run_ids.length)
                })}
              {:else}
                {m.ai_builder_review_lead_loading()}
              {/if}
            </p>
          {/if}
        </div>
        <Button
          variant="ghost"
          size="icon"
          class="size-8 shrink-0"
          aria-label={m.ai_builder_review_close()}
          onclick={onclose}
        >
          <IconX class="size-4" />
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
          <p class="text-secondary text-[0.875rem] text-pretty" data-testid="findings-no-runs">
            {m.ai_builder_review_no_runs()}
          </p>
          {#if omittedCount > 0}
            <p class="text-secondary mt-1.5 text-xs">
              {m.ai_builder_review_omitted({ count: String(omittedCount) })}
            </p>
          {/if}
        {:else if packet}
          {#if findings.length === 0}
            <p class="text-secondary text-[0.875rem] text-pretty" data-testid="findings-none">
              {hiddenCount > 0
                ? m.ai_builder_review_all_hidden()
                : m.ai_builder_review_nothing_found()}
            </p>
          {:else}
            <ul class="flex flex-col gap-2.5" data-testid="findings-list">
              {#each findings as fact (fact.finding_id)}
                {@const described = describeReviewFact(fact, packet.steps)}
                <li
                  class="border-default bg-secondary rounded-lg border px-3.5 py-3"
                  data-finding-id={fact.finding_id}
                >
                  <div class="flex items-start justify-between gap-3">
                    <div class="min-w-0">
                      <p class="text-primary text-[0.9rem] font-semibold first-letter:uppercase">
                        {described.title}
                      </p>
                      <p class="text-secondary mt-0.5 text-[0.8125rem] text-pretty">
                        {described.evidence}
                      </p>
                    </div>
                    <Button
                      variant="ghost"
                      size="sm"
                      class="text-secondary h-7 shrink-0 px-2 text-xs"
                      onclick={() => dismiss(fact)}
                    >
                      {m.ai_builder_review_hide()}
                    </Button>
                  </div>
                  <div class="mt-2.5">
                    <Button size="sm" class="h-8" {disabled} onclick={() => prepare(fact)}>
                      {m.ai_builder_review_prepare()}
                    </Button>
                  </div>
                </li>
              {/each}
            </ul>
          {/if}

          <section
            class="border-default mt-5 border-t pt-4"
            aria-label={m.ai_builder_review_suggestions_title()}
            data-testid="review-suggestions"
          >
            {#if suggestions.status === "closed"}
              <div class="flex flex-col gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  class="h-8 w-fit gap-1.5"
                  disabled={disabled || runCount === 0}
                  onclick={() => onsuggest?.()}
                >
                  <IconSparkles class="size-3.5" aria-hidden="true" />
                  {m.ai_builder_review_suggest()}
                </Button>
                <p class="text-secondary text-xs text-pretty">
                  {m.ai_builder_review_suggest_hint()}
                </p>
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
                  <Button variant="outline" size="sm" class="mt-2.5" onclick={() => onsuggest?.()}>
                    {m.ai_builder_review_retry()}
                  </Button>
                {/if}
              </div>
            {:else}
              {@const judged = suggestions.suggestions}
              <h3 class="text-primary text-[0.9375rem] font-bold">
                {m.ai_builder_review_suggestions_title()}
              </h3>
              <p class="text-secondary mt-0.5 text-xs text-pretty">
                {m.ai_builder_review_suggestions_lead({
                  model: judged.model_id,
                  runs: String(judged.sample.run_ids.length),
                  included: String(judged.sample.excerpts_included),
                  truncated: String(judged.sample.excerpts_truncated),
                  unread: String(
                    judged.sample.excerpts_omitted_by_budget +
                      judged.sample.excerpts_omitted_by_reader +
                      judged.sample.excerpts_not_recorded +
                      judged.sample.excerpts_unavailable
                  )
                })}
              </p>
              {#if judged.suggestions.length === 0}
                <p
                  class="text-secondary mt-3 text-[0.875rem] text-pretty"
                  data-testid="suggestions-none"
                >
                  {m.ai_builder_review_suggestions_none()}
                </p>
              {:else}
                <ul class="mt-3 flex flex-col gap-2.5" data-testid="suggestions-list">
                  {#each judged.suggestions as suggestion, index (index)}
                    <li class="border-default bg-secondary rounded-lg border px-3.5 py-3">
                      <div class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                        <p class="text-primary text-[0.9rem] font-semibold">
                          {suggestionKindLabel(suggestion.kind)}
                        </p>
                        <span class="text-secondary text-xs">
                          {suggestionStepsLabel(suggestion.step_orders)}
                        </span>
                      </div>
                      <p class="text-secondary mt-1 text-[0.8125rem] text-pretty">
                        {suggestion.rationale}
                      </p>
                      <ul class="mt-2 flex flex-col gap-1.5">
                        {#each suggestion.sources as source, sourceIndex (sourceIndex)}
                          <li class="text-xs">
                            <span class="text-secondary">
                              {suggestionSourceLabel(source, judged.sample.run_ids)}:
                            </span>
                            <q class="text-primary">{source.quote}</q>
                          </li>
                        {/each}
                      </ul>
                      <div class="mt-2.5">
                        <Button
                          size="sm"
                          class="h-8"
                          {disabled}
                          onclick={() => investigate(suggestion)}
                        >
                          {m.ai_builder_review_suggestion_investigate()}
                        </Button>
                      </div>
                    </li>
                  {/each}
                </ul>
              {/if}
              <p class="text-secondary mt-3 text-xs text-pretty">
                {m.ai_builder_review_suggestion_disclaimer()}
              </p>
            {/if}
          </section>

          <footer class="border-default mt-4 border-t pt-3 text-xs">
            <p class="text-secondary text-pretty">
              {#if completeness && completeness.kind === "evidence_completeness"}
                {m.ai_builder_review_completeness({
                  complete: String(completeness.runs_with_all_step_results),
                  incomplete: String(completeness.runs_missing_step_results)
                })}
              {/if}
              {#if omittedCount > 0}
                {m.ai_builder_review_omitted({ count: String(omittedCount) })}
              {/if}
            </p>
            {#if hiddenCount > 0}
              <Button
                variant="link"
                class="mt-1 h-auto p-0 text-xs font-semibold"
                onclick={showHidden}
              >
                {m.ai_builder_review_show_hidden({ count: String(hiddenCount) })}
              </Button>
            {/if}
          </footer>
        {/if}
      </div>
    </section>

    <div class="mt-3">
      <Button variant="ghost" size="sm" class="text-secondary -ml-2 h-8 gap-1.5" onclick={onclose}>
        <IconArrowLeft class="size-3.5" />
        {m.ai_builder_review_back()}
      </Button>
    </div>
  </div>
</div>

<style>
  .findings-screen {
    animation: builder-screen-in 0.22s cubic-bezier(0.16, 1, 0.3, 1);
  }
  @keyframes builder-screen-in {
    from {
      opacity: 0.4;
      transform: translateY(6px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }
  @media (prefers-reduced-motion: reduce) {
    .findings-screen {
      animation: none;
    }
  }
</style>
