<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import type { RequirementsSummary } from "./protocol";

  interface Props {
    summary: RequirementsSummary;
    confirmed?: boolean;
    active?: boolean;
    onconfirm?: () => void;
    onchange?: () => void;
  }

  let { summary, confirmed = false, active = true, onconfirm, onchange }: Props = $props();

  // Auto-collapse confirmed summaries to reduce scroll fatigue
  let expanded = $state(!confirmed);

  // When confirmation state changes, collapse
  $effect(() => {
    if (confirmed) expanded = false;
  });
</script>

<Card.Root
  class="mt-3 overflow-hidden transition-[opacity,border-color] duration-250 ease-out {confirmed &&
  !expanded
    ? 'pointer-events-none opacity-60'
    : ''}"
>
  <Collapsible.Root bind:open={expanded}>
    <Card.Header class="px-4 pt-3 pb-0">
      <div class="flex items-center gap-1.5">
        <span class="text-accent-default flex shrink-0 items-center justify-center">
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 20 20"
            fill="currentColor"
            class="size-3.5"
          >
            <path
              fill-rule="evenodd"
              d="M18 10a8 8 0 1 1-16 0 8 8 0 0 1 16 0Zm-7-4a1 1 0 1 1-2 0 1 1 0 0 1 2 0ZM9 9a.75.75 0 0 0 0 1.5h.253a.25.25 0 0 1 .244.304l-.459 2.066A1.75 1.75 0 0 0 10.747 15H11a.75.75 0 0 0 0-1.5h-.253a.25.25 0 0 1-.244-.304l.459-2.066A1.75 1.75 0 0 0 9.253 9H9Z"
              clip-rule="evenodd"
            />
          </svg>
        </span>
        <Card.Title class="text-sm font-[650] tracking-[-0.01em]"
          >{m.ai_builder_requirements_title()}</Card.Title
        >
        {#if confirmed}
          <Collapsible.Trigger
            class="text-accent-default hover:text-accent-stronger ml-auto cursor-pointer rounded bg-transparent px-1.5 py-0.5 text-xs font-medium transition-colors duration-150"
          >
            {expanded ? m.ai_builder_requirements_collapse() : m.ai_builder_requirements_expand()}
          </Collapsible.Trigger>
        {/if}
      </div>
    </Card.Header>

    <Collapsible.Content>
      <Card.Content class="flex flex-col gap-0 px-4 pt-0 pb-3">
        <!-- Summary text -->
        <p class="text-secondary pt-2 text-[0.8125rem] leading-[1.55]">{summary.summary}</p>

        <!-- Key decisions -->
        {#if summary.key_decisions.length > 0}
          <div class="bg-secondary mx-[-0.25rem] mt-2.5 rounded-lg px-2.5 py-2">
            <p class="mb-1.5 text-[0.8125rem] font-[650] tracking-[-0.01em]">
              {m.ai_builder_requirements_decisions()}
            </p>
            <dl class="flex flex-col">
              {#each summary.key_decisions as decision, i (decision.topic)}
                <div
                  class="items-first-baseline grid grid-cols-[auto_1fr] gap-x-2.5 gap-y-1 py-1.5 {i >
                  0
                    ? 'border-default border-t'
                    : ''}"
                >
                  <dt class="text-[0.8125rem] font-semibold whitespace-nowrap">{decision.topic}</dt>
                  <dd class="text-secondary text-[0.8125rem] leading-normal">
                    {decision.decision}
                  </dd>
                </div>
              {/each}
            </dl>
          </div>
        {/if}

        <!-- Input / Output -->
        <Separator class="mt-3" />
        <div class="grid grid-cols-2 gap-3 pt-3">
          <div class="flex flex-col gap-[0.1875rem]">
            <span class="text-muted text-[0.6875rem] font-semibold tracking-[0.04em] uppercase"
              >{m.ai_builder_requirements_input()}</span
            >
            <span class="text-[0.8125rem] leading-normal">{summary.input_description}</span>
          </div>
          <div class="flex flex-col gap-[0.1875rem]">
            <span class="text-muted text-[0.6875rem] font-semibold tracking-[0.04em] uppercase"
              >{m.ai_builder_requirements_output()}</span
            >
            <span class="text-[0.8125rem] leading-normal">{summary.output_description}</span>
          </div>
        </div>

        <!-- Assumptions -->
        {#if summary.assumptions && summary.assumptions.length > 0}
          <div class="bg-accent-default/[0.06] mx-[-0.25rem] mt-2.5 rounded-lg px-2.5 py-2">
            <p class="text-accent-stronger mb-1 text-[0.6875rem] font-semibold">
              {m.ai_builder_assumptions()}
            </p>
            <ul class="flex flex-col gap-[0.1875rem] p-0">
              {#each summary.assumptions as assumption (assumption)}
                <li
                  class="text-accent-default relative pl-3 text-xs leading-[1.45] before:absolute before:top-[0.5em] before:left-0 before:size-1 before:rounded-full before:bg-current before:opacity-40"
                >
                  {assumption}
                </li>
              {/each}
            </ul>
          </div>
        {/if}

        <!-- Manual setup notes -->
        {#if summary.manual_setup_notes && summary.manual_setup_notes.length > 0}
          <div class="bg-accent-default/[0.06] mx-[-0.25rem] mt-2.5 rounded-lg px-2.5 py-2">
            <p class="text-accent-stronger mb-1 text-[0.6875rem] font-semibold">
              {m.ai_builder_requirements_manual_notes()}
            </p>
            <ul class="flex flex-col gap-[0.1875rem] p-0">
              {#each summary.manual_setup_notes as note (note)}
                <li
                  class="text-accent-default relative pl-3 text-xs leading-[1.45] before:absolute before:top-[0.5em] before:left-0 before:size-1 before:rounded-full before:bg-current before:opacity-40"
                >
                  {note}
                </li>
              {/each}
            </ul>
          </div>
        {/if}

        <!-- Actions -->
        {#if !confirmed && active && onconfirm && onchange}
          <div class="mt-1.5 flex gap-1.5 pt-2.5">
            <Button variant="default" size="sm" onclick={onconfirm}>
              {m.ai_builder_requirements_confirm()}
            </Button>
            <Button variant="outline" size="sm" onclick={onchange}>
              {m.ai_builder_requirements_change()}
            </Button>
          </div>
        {:else if !active}
          <p class="text-muted pt-1.5 text-xs font-medium">
            {m.ai_builder_requirements_superseded()}
          </p>
        {/if}
      </Card.Content>
    </Collapsible.Content>

    <!-- Collapsed hint (outside Collapsible.Content so it shows when collapsed) -->
    {#if !expanded && confirmed}
      <Card.Content class="px-4 pt-1 pb-3">
        {#if summary.key_decisions.length > 0}
          <p class="text-muted text-xs leading-[1.4]">
            {summary.key_decisions.map((d) => d.topic).join(" · ")}
          </p>
        {/if}
      </Card.Content>
    {/if}
  </Collapsible.Root>
</Card.Root>
