<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import Info from "@lucide/svelte/icons/info";
  import {
    buildSkillActivationRows,
    getUnmatchedActivationRejections,
    summarizeSkillActivation,
    type SkillActivationDebugRow,
    type SkillActivationEvidence,
    type SkillActivationRejection
  } from "../../skillActivationDebug";
  import ChatDebugSection from "./ChatDebugSection.svelte";
  import CopyableDebugValue from "./CopyableDebugValue.svelte";

  const PAGE_SIZE = 50;

  let { evidence }: { evidence: SkillActivationEvidence } = $props();
  let visibleCount = $state(PAGE_SIZE);
  let previousEvidence: SkillActivationEvidence | undefined;

  const rows = $derived(buildSkillActivationRows(evidence));
  const visibleRows = $derived(rows.slice(0, visibleCount));
  const remainingCount = $derived(Math.max(0, rows.length - visibleCount));
  const summary = $derived(summarizeSkillActivation(evidence));
  const unmatchedRejections = $derived(getUnmatchedActivationRejections(evidence));
  const numberFormatter = $derived(new Intl.NumberFormat(getLocale() === "sv" ? "sv-SE" : "en-US"));

  const status = $derived<"activated" | "none" | "warning">(
    summary.blocked > 0 || summary.rejected > 0
      ? "warning"
      : summary.enteredContext > 0
        ? "activated"
        : "none"
  );
  const STATUS_CLASS = {
    activated: "border-positive-default/40 bg-positive-dimmer text-positive-stronger",
    warning: "border-caution bg-caution text-caution",
    none: ""
  };
  const verdict = $derived(
    [
      summary.available === 1
        ? m.chat_debug_verdict_available_one({ count: "1" })
        : m.chat_debug_verdict_available_other({
            count: numberFormatter.format(summary.available)
          }),
      summary.enteredContext === 1
        ? m.chat_debug_verdict_active_one({ count: "1" })
        : m.chat_debug_verdict_active_other({
            count: numberFormatter.format(summary.enteredContext)
          })
    ].join(" · ")
  );
  // Nothing entered context and no fallback explains it: the model simply
  // never called the activation tool for its on-demand candidates.
  const nothingCalled = $derived(
    summary.enteredContext === 0 &&
      !evidence.fallback_reason &&
      evidence.effective_mode === "selective" &&
      rows.some((row) => row.activationMode === "on_demand")
  );

  const stats = $derived([
    [m.chat_debug_available(), numberFormatter.format(summary.available)],
    [m.chat_debug_entered_context(), numberFormatter.format(summary.enteredContext)],
    [m.chat_debug_blocked(), numberFormatter.format(summary.blocked)],
    [m.chat_debug_rejected(), numberFormatter.format(summary.rejected)],
    ...(evidence.effective_mode === "selective"
      ? [
          [m.chat_debug_rounds(), numberFormatter.format(evidence.activation_rounds ?? 0)],
          [
            m.chat_debug_latency(),
            m.chat_debug_milliseconds({ count: String(evidence.selection_latency_ms ?? 0) })
          ]
        ]
      : [])
  ]);
  const budgetPercent = $derived(
    evidence.skill_context_token_limit > 0
      ? Math.min(100, (evidence.skill_context_tokens / evidence.skill_context_token_limit) * 100)
      : 0
  );

  $effect(() => {
    const currentEvidence = evidence;
    if (previousEvidence && currentEvidence !== previousEvidence) visibleCount = PAGE_SIZE;
    previousEvidence = currentEvidence;
  });

  function modeLabel(mode: SkillActivationEvidence["effective_mode"]): string {
    if (mode === "eager") return m.chat_debug_mode_eager();
    if (mode === "always_only") return m.chat_debug_mode_always_only();
    return m.chat_debug_mode_selective();
  }

  function modeDescription(mode: SkillActivationEvidence["effective_mode"]): string {
    if (mode === "eager") return m.chat_debug_mode_eager_description();
    if (mode === "always_only") return m.chat_debug_mode_always_only_description();
    return m.chat_debug_mode_selective_description();
  }

  function fallbackDescription(
    reason: NonNullable<SkillActivationEvidence["fallback_reason"]>
  ): string {
    const descriptions = {
      model_lacks_tool_calling: m.chat_debug_fallback_model_lacks_tool_calling,
      catalog_budget_exceeded: m.chat_debug_fallback_catalog_budget_exceeded,
      token_measurement_unavailable: m.chat_debug_fallback_token_measurement_unavailable,
      selective_activation_disabled: m.chat_debug_fallback_selective_activation_disabled
    };
    return descriptions[reason]();
  }

  function rejectionDescription(reason: SkillActivationRejection["reason"]): string {
    const descriptions = {
      unknown_key: m.chat_debug_rejection_unknown_key,
      blocked: m.chat_debug_rejection_blocked,
      activation_unavailable: m.chat_debug_rejection_activation_unavailable,
      activation_limit_exceeded: m.chat_debug_rejection_activation_limit_exceeded,
      context_limit_exceeded: m.chat_debug_rejection_context_limit_exceeded,
      model_context_limit_exceeded: m.chat_debug_rejection_model_context_limit_exceeded,
      token_measurement_unavailable: m.chat_debug_rejection_token_measurement_unavailable,
      reserved_tool_collision: m.chat_debug_rejection_reserved_tool_collision
    };
    return descriptions[reason]();
  }

  type Decision = { text: string; tone: "positive" | "destructive" | "muted" };

  function decisions(row: SkillActivationDebugRow): Decision[] {
    const lines: Decision[] = [];
    if (row.candidateState === "blocked") {
      lines.push({ text: m.chat_debug_rejection_blocked(), tone: "destructive" });
    }
    for (const reason of row.rejectionReasons) {
      lines.push({
        text: `${m.chat_debug_outcome_rejected()}: ${rejectionDescription(reason)}`,
        tone: "destructive"
      });
    }
    if (row.outcomes.includes("accepted")) {
      lines.push({ text: m.chat_debug_activated_on_demand(), tone: "positive" });
    } else if (row.activationMode === "always") {
      lines.push({ text: m.chat_debug_initially_active(), tone: "positive" });
    }
    if (row.outcomes.includes("repeated")) {
      lines.push({ text: m.chat_debug_outcome_repeated(), tone: "muted" });
    }
    if (row.activationMode === "on_demand" && row.outcomes.length === 0) {
      lines.push({
        text:
          evidence.effective_mode === "always_only"
            ? m.chat_debug_candidate_always_only()
            : m.chat_debug_candidate_not_called(),
        tone: "muted"
      });
    }
    return lines;
  }

  const DECISION_CLASS = {
    positive: "text-positive-stronger",
    destructive: "text-destructive",
    muted: "text-muted-foreground"
  };
</script>

<ChatDebugSection
  id="chat-debug-section-skills"
  title={m.chat_debug_skill_activation()}
  count={rows.length}
>
  <div class="flex flex-col gap-1.5">
    <div class="flex flex-wrap items-center justify-between gap-x-3 gap-y-1.5">
      <p class="text-sm font-semibold tabular-nums">{verdict}</p>
      <Badge variant="outline" class={STATUS_CLASS[status]}>
        {#if status === "activated"}
          {m.chat_debug_status_activated()}
        {:else if status === "warning"}
          {m.chat_debug_status_warning()}
        {:else}
          {m.chat_debug_status_none()}
        {/if}
      </Badge>
    </div>
    {#if nothingCalled}
      <p class="text-muted-foreground text-sm leading-5">{m.chat_debug_reason_not_called()}</p>
    {/if}
    <p class="text-muted-foreground max-w-[68ch] text-sm leading-5">
      <span class="text-foreground font-medium">{modeLabel(evidence.effective_mode)}.</span>
      {modeDescription(evidence.effective_mode)}
    </p>
  </div>

  {#if evidence.fallback_reason}
    <Alert.Root>
      <Info aria-hidden="true" />
      <Alert.Title>{m.chat_debug_fallback_title()}</Alert.Title>
      <Alert.Description>{fallbackDescription(evidence.fallback_reason)}</Alert.Description>
    </Alert.Root>
  {/if}

  <dl
    class="bg-border -mx-3 grid gap-px {stats.length > 4
      ? 'grid-cols-2 @md:grid-cols-3 @xl:grid-cols-6'
      : 'grid-cols-2 @md:grid-cols-4'}"
  >
    {#each stats as [label, value] (label)}
      <div class="bg-background min-w-0 px-3 py-1.5">
        <dt class="text-muted-foreground truncate text-xs leading-4" title={label}>{label}</dt>
        <dd class="mt-0.5 text-sm font-semibold tabular-nums">{value}</dd>
      </div>
    {/each}
  </dl>

  <div class="flex flex-col gap-1.5">
    <div class="flex items-baseline justify-between gap-3">
      <span class="text-muted-foreground text-xs">{m.chat_debug_token_budget()}</span>
      <span class="text-sm font-medium tabular-nums">
        {m.chat_debug_token_budget_of({
          used: numberFormatter.format(evidence.skill_context_tokens),
          limit: numberFormatter.format(evidence.skill_context_token_limit)
        })}
        {#if evidence.token_count_source !== "litellm"}
          <span class="text-muted-foreground font-normal">
            ({m.chat_debug_token_source_fallback_estimate()})
          </span>
        {/if}
      </span>
    </div>
    <div
      role="progressbar"
      aria-label={m.chat_debug_token_budget()}
      aria-valuemin={0}
      aria-valuemax={evidence.skill_context_token_limit}
      aria-valuenow={evidence.skill_context_tokens}
      class="bg-muted h-1 w-full overflow-hidden rounded-full"
    >
      <div
        class="bg-accent-default h-full rounded-full {evidence.skill_context_tokens > 0
          ? 'min-w-1'
          : ''}"
        style="width: {budgetPercent}%"
      ></div>
    </div>
  </div>

  <div class="flex flex-col gap-2">
    <h3 class="text-sm font-semibold">{m.chat_debug_candidate_order()}</h3>
    {#if rows.length === 0}
      <div class="flex flex-col gap-1 py-1">
        <p class="text-sm font-medium">{m.chat_debug_zero_skills_title()}</p>
        <p class="text-muted-foreground text-sm">{m.chat_debug_zero_skills_description()}</p>
      </div>
    {:else}
      <ol class="flex flex-col gap-2">
        {#each visibleRows as row (row.skill_revision_id)}
          <li class="border-border flex flex-col gap-2 rounded-lg border px-4 py-3">
            <div class="flex min-w-0 items-start justify-between gap-3">
              <div class="min-w-0">
                <p class="text-sm leading-5 font-semibold break-words">
                  {row.display_name ?? row.slug ?? row.skill_id}
                </p>
                <p class="text-muted-foreground text-xs leading-4 break-words">
                  {#if row.display_name && row.slug}
                    <span class="break-all">{row.slug}</span> ·
                  {/if}
                  {m.chat_debug_candidate_position({ position: String(row.position + 1) })} ·
                  {m.chat_debug_revision({ number: String(row.revision_number) })} ·
                  {row.source === "space"
                    ? m.chat_debug_source_space()
                    : m.chat_debug_source_organization()}
                </p>
              </div>
              <div class="flex shrink-0 flex-wrap justify-end gap-1.5">
                {#if row.activationMode === "always"}
                  <Badge variant="outline">{m.skills_activation_mode_always()}</Badge>
                {:else if row.activationMode === "on_demand"}
                  <Badge variant="outline">{m.skills_activation_mode_on_demand()}</Badge>
                {/if}
                {#if row.candidateState === "blocked"}
                  <Badge variant="destructive">{m.chat_debug_outcome_blocked()}</Badge>
                {:else if row.outcomes.includes("rejected")}
                  <Badge variant="destructive">{m.chat_debug_outcome_rejected()}</Badge>
                {:else if row.outcomes.includes("accepted") || row.activationMode === "always"}
                  <Badge variant="outline" class={STATUS_CLASS.activated}>
                    {m.chat_debug_outcome_activated()}
                  </Badge>
                {:else}
                  <Badge variant="outline">{m.chat_debug_outcome_available()}</Badge>
                {/if}
              </div>
            </div>

            <ul class="flex flex-col gap-0.5 text-sm leading-5">
              {#each decisions(row) as decision, index (`${decision.text}:${index}`)}
                <li class={DECISION_CLASS[decision.tone]}>{decision.text}</li>
              {/each}
            </ul>

            <Collapsible.Root>
              <Collapsible.Trigger
                class="text-muted-foreground hover:text-foreground focus-visible:ring-ring -mx-1 flex items-center gap-1 rounded px-1 py-0.5 text-xs font-medium focus-visible:ring-1 focus-visible:outline-none [&[data-state=open]>svg]:rotate-180"
              >
                <ChevronDown
                  aria-hidden="true"
                  class="size-3.5 transition-transform motion-reduce:transition-none"
                />
                {m.chat_debug_technical_details()}
              </Collapsible.Trigger>
              <Collapsible.Content>
                <dl class="mt-2 flex flex-col gap-2">
                  <CopyableDebugValue
                    label={m.chat_debug_skill_revision_id()}
                    value={row.skill_revision_id}
                  />
                  <CopyableDebugValue
                    label={m.chat_debug_activation_key()}
                    value={row.activationKey}
                  />
                  <CopyableDebugValue label={m.chat_debug_digest()} value={row.content_digest} />
                </dl>
              </Collapsible.Content>
            </Collapsible.Root>
          </li>
        {/each}
      </ol>

      {#if remainingCount > 0}
        <Button class="self-start" variant="outline" onclick={() => (visibleCount += PAGE_SIZE)}>
          <ChevronDown data-icon="inline-start" aria-hidden="true" />
          {m.chat_debug_show_more({ count: String(Math.min(PAGE_SIZE, remainingCount)) })}
        </Button>
      {/if}
    {/if}
  </div>

  {#if unmatchedRejections.length > 0}
    <Alert.Root variant="destructive">
      <Alert.Title>{m.chat_debug_unmatched_rejections()}</Alert.Title>
      <Alert.Description>
        <ul class="mt-1 flex flex-col gap-2">
          {#each unmatchedRejections as rejection, rejectionIndex (`${rejection.activation_key}:${rejection.reason}:${rejectionIndex}`)}
            <li class="break-all">
              <strong>{rejection.activation_key}</strong>: {rejectionDescription(rejection.reason)}
            </li>
          {/each}
        </ul>
      </Alert.Description>
    </Alert.Root>
  {/if}
</ChatDebugSection>
