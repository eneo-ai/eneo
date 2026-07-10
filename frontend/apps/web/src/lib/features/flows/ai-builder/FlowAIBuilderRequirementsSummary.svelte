<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import type { RequirementsSummary } from "./protocol";

  interface Props {
    summary: RequirementsSummary;
    userRequest?: string | null;
    confirmed?: boolean;
    active?: boolean;
    onconfirm?: () => void;
    onchange?: () => void;
  }

  let {
    summary,
    userRequest = null,
    confirmed = false,
    active = true,
    onconfirm,
    onchange
  }: Props = $props();

  // Manual reveal after confirmation; before confirmation the summary stays expanded.
  let userExpanded = $state(false);
  const expanded = $derived(!confirmed || userExpanded);
  // Assumptions are supporting detail, collapsed so the summary reads fast.
  let assumptionsExpanded = $state(false);

  function toggleExpanded() {
    userExpanded = !userExpanded;
  }

  const hasAssumptions = $derived((summary.assumptions ?? []).length > 0);
  const hasManualNotes = $derived((summary.manual_setup_notes ?? []).length > 0);
  const hasDecisions = $derived(summary.key_decisions.length > 0);
</script>

<section
  class="border-default bg-primary ring-foreground/10 group mt-3 overflow-hidden rounded-xl border ring-1 transition-[opacity,box-shadow] duration-200 ease-out
    {confirmed && !expanded ? 'opacity-70' : 'shadow-sm'}"
  aria-label={m.ai_builder_requirements_title()}
>
  <header class="flex items-center gap-2.5 px-4 pt-3.5 pb-2">
    <span
      class="bg-accent-default/10 text-accent-default flex size-6 shrink-0 items-center justify-center rounded-md"
      aria-hidden="true"
    >
      <svg
        xmlns="http://www.w3.org/2000/svg"
        viewBox="0 0 20 20"
        fill="currentColor"
        class="size-3.5"
      >
        <path
          fill-rule="evenodd"
          d="M16.704 4.153a.75.75 0 0 1 .143 1.052l-8 10.5a.75.75 0 0 1-1.127.075l-4.5-4.5a.75.75 0 0 1 1.06-1.06l3.898 3.897 7.473-9.821a.75.75 0 0 1 1.053-.143Z"
          clip-rule="evenodd"
        />
      </svg>
    </span>

    <h2 class="text-primary text-sm font-semibold tracking-[-0.01em]">
      {m.ai_builder_requirements_title()}
    </h2>

    {#if confirmed}
      <button
        type="button"
        class="text-accent-default hover:text-accent-stronger focus-visible:ring-accent-default/30 ml-auto cursor-pointer rounded-md px-2 py-0.5 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none"
        onclick={toggleExpanded}
      >
        {expanded ? m.ai_builder_requirements_collapse() : m.ai_builder_requirements_expand()}
      </button>
    {/if}
  </header>

  {#if expanded}
    <div class="flex flex-col gap-4 px-4 pt-2 pb-4">
      <div class="border-default border-b pb-3">
        <p class="text-primary text-[0.9375rem] leading-[1.55]">{summary.summary}</p>
      </div>

      {#if userRequest}
        <section class="border-default bg-secondary/30 rounded-lg border px-3 py-2.5">
          <h3 class="text-muted mb-1 text-xs font-semibold tracking-[0.06em] uppercase">
            {m.ai_builder_requirements_user_request()}
          </h3>
          <p class="text-secondary text-[0.8125rem] leading-relaxed whitespace-pre-wrap">
            {userRequest}
          </p>
        </section>
      {/if}

      {#if hasDecisions}
        <section class="flex flex-col gap-2">
          <h3 class="text-muted text-xs font-semibold tracking-[0.06em] uppercase">
            {m.ai_builder_requirements_decisions()}
          </h3>
          <dl class="divide-default flex flex-col divide-y">
            {#each summary.key_decisions as decision (decision.topic)}
              <div class="grid gap-x-4 gap-y-1 py-2 first:pt-0 last:pb-0 sm:grid-cols-[12rem_1fr]">
                <dt class="text-primary text-[0.8125rem] font-semibold">{decision.topic}</dt>
                <dd class="text-secondary text-[0.8125rem] leading-normal">
                  {decision.decision}
                </dd>
              </div>
            {/each}
          </dl>
        </section>
      {/if}

      <div class="border-default grid gap-x-4 gap-y-3 border-t pt-3 sm:grid-cols-2">
        <div class="flex flex-col gap-1">
          <span class="text-muted text-xs font-semibold tracking-[0.06em] uppercase">
            {m.ai_builder_requirements_input()}
          </span>
          <span class="text-primary text-[0.8125rem] leading-snug">{summary.input_description}</span
          >
        </div>
        <div class="flex flex-col gap-1">
          <span class="text-muted text-xs font-semibold tracking-[0.06em] uppercase">
            {m.ai_builder_requirements_output()}
          </span>
          <span class="text-primary text-[0.8125rem] leading-snug"
            >{summary.output_description}</span
          >
        </div>
      </div>

      {#if hasAssumptions}
        <section class="flex flex-col gap-1.5">
          <button
            type="button"
            class="text-muted hover:text-primary focus-visible:ring-accent-default/30 flex w-fit items-center gap-1.5 rounded text-xs font-semibold tracking-[0.06em] uppercase transition-colors focus-visible:ring-2 focus-visible:outline-none"
            aria-expanded={assumptionsExpanded}
            onclick={() => (assumptionsExpanded = !assumptionsExpanded)}
          >
            <span>{m.ai_builder_assumptions()} ({(summary.assumptions ?? []).length})</span>
            <svg
              xmlns="http://www.w3.org/2000/svg"
              viewBox="0 0 16 16"
              fill="currentColor"
              class="size-3.5 transition-transform duration-200 ease-out {assumptionsExpanded
                ? 'rotate-180'
                : ''}"
              aria-hidden="true"
            >
              <path
                fill-rule="evenodd"
                d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z"
                clip-rule="evenodd"
              />
            </svg>
          </button>
          {#if assumptionsExpanded}
            <ul class="flex flex-col gap-1 p-0">
              {#each summary.assumptions ?? [] as assumption (assumption)}
                <li class="text-secondary flex items-start gap-2 text-[0.8125rem] leading-snug">
                  <span
                    class="bg-accent-default mt-[0.55em] block size-1.5 shrink-0 rounded-full opacity-70"
                    aria-hidden="true"
                  ></span>
                  <span>{assumption}</span>
                </li>
              {/each}
            </ul>
          {/if}
        </section>
      {/if}

      {#if hasManualNotes}
        <section class="flex flex-col gap-1.5">
          <span class="text-muted text-xs font-semibold tracking-[0.06em] uppercase">
            {m.ai_builder_requirements_manual_notes()}
          </span>
          <ul class="flex flex-col gap-1 p-0">
            {#each summary.manual_setup_notes ?? [] as note (note)}
              <li class="text-secondary flex items-start gap-2 text-[0.8125rem] leading-snug">
                <span
                  class="bg-muted mt-[0.55em] block size-1 shrink-0 rounded-full opacity-60"
                  aria-hidden="true"
                ></span>
                <span>{note}</span>
              </li>
            {/each}
          </ul>
        </section>
      {/if}

      {#if !confirmed && active && onconfirm && onchange}
        <div class="flex flex-wrap justify-end gap-2 pt-1">
          <Button variant="outline" size="sm" onclick={onchange}>
            {m.ai_builder_requirements_change()}
          </Button>
          <Button variant="default" size="sm" onclick={onconfirm}>
            {m.ai_builder_requirements_confirm()}
          </Button>
        </div>
      {:else if !active}
        <p class="text-muted text-xs font-medium">
          {m.ai_builder_requirements_superseded()}
        </p>
      {/if}
    </div>
  {:else if confirmed}
    <div class="px-4 pb-3.5">
      {#if hasDecisions}
        <p class="text-muted text-xs leading-snug">
          {summary.key_decisions.map((d) => d.topic).join(" · ")}
        </p>
      {/if}
    </div>
  {/if}
</section>
