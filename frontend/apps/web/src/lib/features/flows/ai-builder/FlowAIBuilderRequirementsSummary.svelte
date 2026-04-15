<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import type { RequirementsSummary } from "./protocol";

  interface Props {
    summary: RequirementsSummary;
    confirmed?: boolean;
    active?: boolean;
    onconfirm?: () => void;
    onchange?: () => void;
  }

  let { summary, confirmed = false, active = true, onconfirm, onchange }: Props = $props();

  // Collapsible state. Pre-confirmation the summary is always fully expanded so the
  // user can review and act. After confirmation the user may manually reveal details
  // via the trigger; each toggle flips `userExpanded`, and we derive the effective
  // `expanded` from confirmation + user intent without needing an $effect write-back.
  let userExpanded = $state(false);
  const expanded = $derived(!confirmed || userExpanded);

  function handleOpenChange(next: boolean) {
    // bits-ui only fires this when the trigger is rendered (confirmed state).
    userExpanded = next;
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
  <Collapsible.Root open={expanded} onOpenChange={handleOpenChange}>
    <!-- Header -->
    <header class="flex items-center gap-2.5 px-4 pt-3.5 pb-0.5">
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
        <Collapsible.Trigger
          class="text-accent-default hover:text-accent-stronger focus-visible:ring-accent-default/30 ml-auto cursor-pointer rounded-md px-2 py-0.5 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none"
        >
          {expanded ? m.ai_builder_requirements_collapse() : m.ai_builder_requirements_expand()}
        </Collapsible.Trigger>
      {/if}
    </header>

    <Collapsible.Content>
      <div class="flex flex-col gap-4 px-4 pt-3 pb-4">
        <!-- Lead summary -->
        <p class="text-secondary text-[0.8125rem] leading-[1.55]">{summary.summary}</p>

        <!-- Decisions -->
        {#if hasDecisions}
          <div class="border-default bg-secondary/40 rounded-lg border px-3 py-2.5">
            <h3
              class="text-primary mb-1.5 text-[0.75rem] font-semibold tracking-[0.02em] uppercase"
            >
              {m.ai_builder_requirements_decisions()}
            </h3>
            <dl class="divide-default flex flex-col divide-y">
              {#each summary.key_decisions as decision (decision.topic)}
                <div class="grid grid-cols-[9rem_1fr] gap-x-3 gap-y-1 py-1.5 first:pt-0 last:pb-0">
                  <dt class="text-primary text-[0.8125rem] font-medium">{decision.topic}</dt>
                  <dd class="text-secondary text-[0.8125rem] leading-normal">
                    {decision.decision}
                  </dd>
                </div>
              {/each}
            </dl>
          </div>
        {/if}

        <!-- Input / Output -->
        <div class="grid gap-x-4 gap-y-3 sm:grid-cols-2">
          <div class="flex flex-col gap-1">
            <span class="text-muted text-[0.6875rem] font-semibold tracking-[0.06em] uppercase">
              {m.ai_builder_requirements_input()}
            </span>
            <span class="text-primary text-[0.8125rem] leading-snug"
              >{summary.input_description}</span
            >
          </div>
          <div class="flex flex-col gap-1">
            <span class="text-muted text-[0.6875rem] font-semibold tracking-[0.06em] uppercase">
              {m.ai_builder_requirements_output()}
            </span>
            <span class="text-primary text-[0.8125rem] leading-snug"
              >{summary.output_description}</span
            >
          </div>
        </div>

        <!-- Assumptions as chips -->
        {#if hasAssumptions}
          <div class="flex flex-col gap-1.5">
            <span class="text-muted text-[0.6875rem] font-semibold tracking-[0.06em] uppercase">
              {m.ai_builder_assumptions()}
            </span>
            <ul class="flex flex-wrap gap-1.5 p-0">
              {#each summary.assumptions ?? [] as assumption (assumption)}
                <li
                  class="border-accent-default/25 bg-accent-default/8 text-accent-stronger rounded-full border px-2.5 py-0.5 text-[0.75rem] leading-normal"
                >
                  {assumption}
                </li>
              {/each}
            </ul>
          </div>
        {/if}

        <!-- Manual setup notes — kept as list, calmer styling -->
        {#if hasManualNotes}
          <div class="flex flex-col gap-1.5">
            <span class="text-muted text-[0.6875rem] font-semibold tracking-[0.06em] uppercase">
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
          </div>
        {/if}

        <!-- Actions — right aligned -->
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
    </Collapsible.Content>

    <!-- Collapsed hint shown below header, outside content, when confirmed -->
    {#if !expanded && confirmed}
      <div class="px-4 pb-3.5">
        {#if hasDecisions}
          <p class="text-muted text-xs leading-snug">
            {summary.key_decisions.map((d) => d.topic).join(" · ")}
          </p>
        {/if}
      </div>
    {/if}
  </Collapsible.Root>
</section>
