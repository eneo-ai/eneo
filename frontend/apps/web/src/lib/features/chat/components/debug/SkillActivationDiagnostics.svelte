<script lang="ts">
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import Info from "@lucide/svelte/icons/info";
  import {
    buildSkillActivationRows,
    getUnmatchedActivationRejections,
    summarizeSkillActivation,
    type SkillActivationEvidence,
    type SkillActivationRejection
  } from "../../skillActivationDebug";
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
</script>

<Separator />

<section class="flex flex-col gap-5 px-5 py-5" aria-labelledby="chat-debug-skill-activation">
  <div class="flex flex-col gap-2">
    <div class="flex flex-wrap items-center gap-2">
      <h2 id="chat-debug-skill-activation" class="text-sm font-semibold">
        {m.chat_debug_skill_activation()}
      </h2>
      <Badge variant="outline">{modeLabel(evidence.effective_mode)}</Badge>
    </div>
    <p class="text-muted-foreground max-w-[68ch] text-sm leading-5">
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

  <dl class="border-border grid grid-cols-2 border-y sm:grid-cols-4">
    {@render Count(m.chat_debug_available(), summary.available)}
    {@render Count(m.chat_debug_entered_context(), summary.enteredContext)}
    {@render Count(m.chat_debug_blocked(), summary.blocked)}
    {@render Count(m.chat_debug_rejected(), summary.rejected)}
  </dl>

  <dl class="grid grid-cols-2 gap-x-5 gap-y-4 text-sm">
    <CopyableDebugValue label={m.chat_debug_model_route()} value={evidence.selected_model_route} />
    <CopyableDebugValue label={m.chat_debug_model_id()} value={evidence.selected_model_id} />
    <div>
      <dt class="text-muted-foreground text-xs">{m.chat_debug_token_budget()}</dt>
      <dd class="mt-0.5 font-medium tabular-nums">
        {numberFormatter.format(evidence.skill_context_tokens)} /
        {numberFormatter.format(evidence.skill_context_token_limit)}
      </dd>
    </div>
    <div>
      <dt class="text-muted-foreground text-xs">{m.chat_debug_token_source()}</dt>
      <dd class="mt-0.5 font-medium">
        {evidence.token_count_source === "litellm"
          ? m.chat_debug_token_source_litellm()
          : m.chat_debug_token_source_fallback_estimate()}
      </dd>
    </div>
    <div>
      <dt class="text-muted-foreground text-xs">{m.chat_debug_rounds()}</dt>
      <dd class="mt-0.5 font-medium tabular-nums">
        {numberFormatter.format(evidence.activation_rounds ?? 0)}
      </dd>
    </div>
    <div>
      <dt class="text-muted-foreground text-xs">{m.chat_debug_latency()}</dt>
      <dd class="mt-0.5 font-medium tabular-nums">
        {m.chat_debug_milliseconds({ count: String(evidence.selection_latency_ms ?? 0) })}
      </dd>
    </div>
  </dl>

  <div class="flex flex-col gap-3">
    <h3 class="text-sm font-semibold">{m.chat_debug_candidate_order()}</h3>
    {#if rows.length === 0}
      <div class="flex flex-col gap-1 py-2">
        <p class="text-sm font-medium">{m.chat_debug_zero_skills_title()}</p>
        <p class="text-muted-foreground text-sm">{m.chat_debug_zero_skills_description()}</p>
      </div>
    {:else}
      <ol class="border-border border-t">
        {#each visibleRows as row (row.skill_revision_id)}
          <li class="border-border flex flex-col gap-3 border-b py-4">
            <div class="flex min-w-0 items-start justify-between gap-3">
              <p class="break-all text-sm font-semibold">{row.skill_id}</p>
              <span class="text-muted-foreground shrink-0 text-xs tabular-nums">
                {m.chat_debug_candidate_position({ position: String(row.position + 1) })}
              </span>
            </div>

            <div class="flex flex-wrap gap-1.5">
              {#if row.candidateState === "available"}
                <Badge variant="outline">{m.chat_debug_outcome_available()}</Badge>
              {/if}
              {#if row.activationMode === "always"}
                <Badge variant="secondary">{m.chat_debug_initially_active()}</Badge>
                <Badge variant="outline">{m.chat_debug_activation_always()}</Badge>
              {:else if row.activationMode === "on_demand" && row.outcomes.includes("accepted")}
                <Badge>{m.chat_debug_activated_on_demand()}</Badge>
              {:else if row.activationMode === "on_demand"}
                <Badge variant="outline">{m.chat_debug_activation_on_demand()}</Badge>
              {/if}
              {#if row.outcomes.includes("repeated")}
                <Badge variant="secondary">{m.chat_debug_outcome_repeated()}</Badge>
              {/if}
              {#if row.outcomes.includes("blocked")}
                <Badge variant="destructive">{m.chat_debug_outcome_blocked()}</Badge>
              {/if}
              {#if row.outcomes.includes("rejected")}
                <Badge variant="destructive">{m.chat_debug_outcome_rejected()}</Badge>
              {/if}
            </div>

            {#if evidence.effective_mode === "always_only" && row.activationMode === "on_demand"}
              <p class="text-muted-foreground text-sm leading-5">
                {m.chat_debug_candidate_always_only()}
              </p>
            {/if}

            {#if row.rejectionReasons.length > 0}
              <ul class="text-destructive flex flex-col gap-1 text-sm leading-5">
                {#each row.rejectionReasons as reason, reasonIndex (`${reason}:${reasonIndex}`)}
                  <li>{rejectionDescription(reason)}</li>
                {/each}
              </ul>
            {/if}

            <dl class="grid gap-x-5 gap-y-3 sm:grid-cols-2">
              <CopyableDebugValue
                label={m.chat_debug_skill_revision_id()}
                value={row.skill_revision_id}
              />
              <div>
                <dt class="text-muted-foreground text-xs">{m.chat_debug_revision_and_source()}</dt>
                <dd class="mt-0.5 break-words text-xs font-medium">
                  {m.chat_debug_revision({ number: String(row.revision_number) })},
                  {row.source === "space"
                    ? m.chat_debug_source_space()
                    : m.chat_debug_source_organization()}
                </dd>
              </div>
              <CopyableDebugValue label={m.chat_debug_activation_key()} value={row.activationKey} />
              <CopyableDebugValue label={m.chat_debug_digest()} value={row.content_digest} />
            </dl>
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
</section>

{#snippet Count(label: string, value: number)}
  <div class="border-border px-3 py-2.5 not-last:border-r">
    <dt class="text-muted-foreground text-xs leading-4">{label}</dt>
    <dd class="mt-0.5 text-sm font-semibold tabular-nums">{numberFormatter.format(value)}</dd>
  </div>
{/snippet}
