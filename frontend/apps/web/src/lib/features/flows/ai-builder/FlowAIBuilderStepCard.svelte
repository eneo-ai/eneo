<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import { Separator } from "$lib/components/ui/separator/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import type { StepChangeKind, StepSpec } from "./protocol";

  interface Props {
    step: StepSpec;
    stepNumber: number;
    changeKind?: StepChangeKind;
    isFirst?: boolean;
    isLast?: boolean;
    planStatus?: string;
    onsuggestchange?: (prefill: string) => void;
    resolveModelName?: (ref: string | null) => string | null;
  }

  let {
    step,
    stepNumber,
    changeKind = step.existing_step_ref ? "unchanged" : "added",
    isFirst = false,
    isLast = false,
    planStatus = "",
    onsuggestchange,
    resolveModelName
  }: Props = $props();

  let showDetails = $state(false);
  let instructionsExpanded = $state(false);

  const inputSourceLabel = $derived(
    (
      {
        flow_input: m.ai_builder_step_flow_input(),
        previous_step: m.ai_builder_step_previous_step(),
        all_previous_steps: m.ai_builder_step_all_previous()
      } as Record<string, string>
    )[step.input_source] ?? step.input_source
  );
</script>

<div
  class="animate-in fade-in slide-in-from-bottom-2 relative"
  style:animation-delay="{stepNumber * 60}ms"
  style:animation-fill-mode="both"
  class:mt-3={!isFirst}
>
  <Collapsible.Root bind:open={showDetails}>
    <Card.Root
      class="group/step overflow-hidden transition-all duration-300 ease-out
        {changeKind === 'added'
        ? 'border-l-positive-default border-l-[3px]'
        : changeKind === 'modified'
          ? 'border-l-warning-default border-l-[3px]'
          : ''}
        {showDetails
        ? 'border-accent-default/25 ring-accent-default/10 shadow-[0_8px_30px_-12px_rgba(0,0,0,0.1)] ring-1'
        : 'hover:border-stronger/60 hover:shadow-[0_4px_20px_-8px_rgba(0,0,0,0.08)]'}"
    >
      <Collapsible.Trigger
        class="hover:bg-hover-dimmer/30 w-full cursor-pointer text-left transition-colors"
      >
        <Card.Header class="gap-3 px-5 py-4">
          <div class="flex items-center justify-between gap-4">
            <!-- Step number + name -->
            <div class="flex min-w-0 items-center gap-3">
              <span
                class="flex size-8 shrink-0 items-center justify-center rounded-xl text-sm font-bold transition-all duration-200
                  {changeKind === 'added'
                  ? 'bg-positive-dimmer text-positive-stronger'
                  : changeKind === 'modified'
                    ? 'bg-warning-dimmer text-warning-stronger'
                    : 'bg-accent-default/8 text-accent-default group-hover/step:bg-accent-default/12'}"
              >
                {stepNumber}
              </span>
              <div class="min-w-0">
                <Card.Title class="truncate text-[0.9375rem] font-semibold tracking-[-0.01em]">
                  {step.name}
                </Card.Title>
              </div>
            </div>

            <!-- Badges + chevron -->
            <div class="flex shrink-0 items-center gap-2">
              {#if changeKind === "added"}
                <Badge
                  variant="outline"
                  class="border-positive-default/25 bg-positive-dimmer/60 text-positive-stronger"
                >
                  {m.ai_builder_badge_new()}
                </Badge>
              {:else if changeKind === "modified"}
                <Badge
                  variant="outline"
                  class="border-warning-default/25 bg-warning-dimmer/60 text-warning-stronger"
                >
                  {m.ai_builder_badge_modified()}
                </Badge>
              {/if}
              <div
                class="group-hover/step:bg-hover-default flex size-6 items-center justify-center rounded-md transition-colors"
              >
                <svg
                  xmlns="http://www.w3.org/2000/svg"
                  viewBox="0 0 16 16"
                  fill="currentColor"
                  class="text-muted size-3.5 transition-transform duration-300 ease-[cubic-bezier(0.16,1,0.3,1)] {showDetails
                    ? 'rotate-180'
                    : ''}"
                >
                  <path
                    fill-rule="evenodd"
                    d="M4.22 6.22a.75.75 0 0 1 1.06 0L8 8.94l2.72-2.72a.75.75 0 1 1 1.06 1.06l-3.25 3.25a.75.75 0 0 1-1.06 0L4.22 7.28a.75.75 0 0 1 0-1.06Z"
                    clip-rule="evenodd"
                  />
                </svg>
              </div>
            </div>
          </div>

          <!-- IO summary — clean pill-like metadata -->
          <div class="flex flex-wrap items-center gap-2 pl-11 text-xs">
            <span
              class="bg-secondary/40 text-muted inline-flex items-center gap-1.5 rounded-md px-2 py-0.5"
            >
              <span class="font-medium">{m.ai_builder_step_input()}:</span>
              <span class="text-secondary">{inputSourceLabel}</span>
              <span class="text-muted/60">&rarr;</span>
              <span class="text-secondary">{step.input_type}</span>
            </span>
            <span
              class="bg-secondary/40 text-muted inline-flex items-center gap-1.5 rounded-md px-2 py-0.5"
            >
              <span class="font-medium">{m.ai_builder_step_output()}:</span>
              <span class="text-secondary">{step.output_type}</span>
              {#if step.output_mode !== "pass_through"}
                <span class="text-muted/60">({step.output_mode})</span>
              {/if}
            </span>
          </div>
        </Card.Header>
      </Collapsible.Trigger>

      <Collapsible.Content>
        <Separator />
        <Card.Content class="bg-secondary/20 flex flex-col gap-4 px-5 py-4 pl-[3.5rem]">
          <!-- Instructions -->
          {#if step.assistant_spec.instructions}
            <div class="space-y-1.5">
              <span class="text-muted text-[11px] font-semibold tracking-[0.05em] uppercase">
                {m.ai_builder_step_instructions()}
              </span>
              <div class="relative {!instructionsExpanded ? 'max-h-28 overflow-hidden' : ''}">
                <p
                  class="text-secondary max-w-[60ch] text-[13px] leading-relaxed whitespace-pre-wrap"
                >
                  {step.assistant_spec.instructions}
                </p>
                {#if !instructionsExpanded}
                  <div
                    class="from-secondary/20 pointer-events-none absolute inset-x-0 bottom-0 h-10 bg-gradient-to-t to-transparent"
                  ></div>
                {/if}
              </div>
              {#if step.assistant_spec.instructions.length > 300}
                <button
                  class="text-accent-default hover:text-accent-stronger text-xs font-medium transition-colors hover:underline"
                  onclick={(e) => {
                    e.stopPropagation();
                    instructionsExpanded = !instructionsExpanded;
                  }}
                >
                  {instructionsExpanded ? m.ai_builder_show_less() : m.ai_builder_show_more()}
                </button>
              {/if}
            </div>
          {/if}

          <!-- Metadata grid -->
          {#if step.assistant_spec.model_ref || step.assistant_spec.knowledge_refs.length > 0}
            <div class="grid gap-x-6 gap-y-2 sm:grid-cols-2">
              {#if step.assistant_spec.model_ref}
                <div>
                  <span class="text-muted text-[11px] font-semibold tracking-[0.05em] uppercase"
                    >{m.ai_builder_step_model()}</span
                  >
                  <p class="text-secondary mt-0.5 text-[13px]">
                    {resolveModelName?.(step.assistant_spec.model_ref) ??
                      step.assistant_spec.model_ref}
                  </p>
                </div>
              {/if}
              {#if step.assistant_spec.knowledge_refs.length > 0}
                <div>
                  <span class="text-muted text-[11px] font-semibold tracking-[0.05em] uppercase"
                    >{m.ai_builder_step_knowledge()}</span
                  >
                  <p class="text-secondary mt-0.5 text-[13px]">
                    {step.assistant_spec.knowledge_refs.join(", ")}
                  </p>
                </div>
              {/if}
            </div>
          {/if}

          <!-- Bindings -->
          {#if step.input_bindings}
            <div>
              <span class="text-muted text-[11px] font-semibold tracking-[0.05em] uppercase"
                >{m.ai_builder_step_bindings()}</span
              >
              <pre
                class="border-default/60 bg-primary text-secondary mt-1.5 overflow-x-auto rounded-lg border px-3 py-2 font-mono text-xs leading-relaxed">{JSON.stringify(
                  step.input_bindings,
                  null,
                  2
                )}</pre>
            </div>
          {/if}

          <!-- Contracts -->
          {#if step.output_contract?.properties}
            <div>
              <span class="text-muted text-[11px] font-semibold tracking-[0.05em] uppercase"
                >{m.ai_builder_step_output_contract()}</span
              >
              <div class="mt-1.5 space-y-0.5">
                {#each Object.entries(step.output_contract.properties) as [name, schema]}
                  <div class="flex items-baseline gap-2 text-[13px]">
                    <code class="text-accent-default font-semibold">{name}</code>
                    <Badge variant="outline" class="text-[10px]">{schema.type ?? "object"}</Badge>
                    {#if schema.description}
                      <span class="text-muted">{schema.description}</span>
                    {/if}
                  </div>
                {/each}
              </div>
            </div>
          {/if}

          {#if step.input_contract?.properties}
            <div>
              <span class="text-muted text-[11px] font-semibold tracking-[0.05em] uppercase"
                >{m.ai_builder_step_input_contract()}</span
              >
              <div class="mt-1.5 space-y-0.5">
                {#each Object.entries(step.input_contract.properties) as [name, schema]}
                  <div class="flex items-baseline gap-2 text-[13px]">
                    <code class="text-accent-default font-semibold">{name}</code>
                    <Badge variant="outline" class="text-[10px]">{schema.type ?? "object"}</Badge>
                    {#if schema.description}
                      <span class="text-muted">{schema.description}</span>
                    {/if}
                  </div>
                {/each}
              </div>
            </div>
          {/if}

          <!-- MCP warning -->
          {#if step.mcp_policy === "restricted"}
            <div
              class="border-warning-default/30 bg-warning-dimmer/50 text-warning-stronger flex items-center gap-2 rounded-lg border px-3 py-2 text-xs"
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 16 16"
                fill="currentColor"
                class="size-3.5 shrink-0"
              >
                <path
                  fill-rule="evenodd"
                  d="M6.701 2.25c.577-1 2.02-1 2.598 0l5.196 9a1.5 1.5 0 0 1-1.299 2.25H2.804a1.5 1.5 0 0 1-1.3-2.25l5.197-9ZM8 4a.75.75 0 0 1 .75.75v3a.75.75 0 0 1-1.5 0v-3A.75.75 0 0 1 8 4Zm0 8a1 1 0 1 0 0-2 1 1 0 0 0 0 2Z"
                  clip-rule="evenodd"
                />
              </svg>
              {m.ai_builder_mcp_restricted()}
            </div>
          {/if}

          <!-- Suggest change action -->
          {#if planStatus === "proposed"}
            <button
              class="border-accent-default/15 bg-accent-default/5 text-accent-default hover:border-accent-default/30 hover:bg-accent-default/10 mt-1 inline-flex w-fit items-center gap-1.5 rounded-full border px-3.5 py-1.5 text-xs font-medium transition-all duration-200 hover:shadow-sm active:scale-[0.98]"
              onclick={(e) => {
                e.stopPropagation();
                onsuggestchange?.(`${m.ai_builder_suggest_change_prefix()} '${step.name}': `);
              }}
            >
              <svg
                xmlns="http://www.w3.org/2000/svg"
                viewBox="0 0 16 16"
                fill="currentColor"
                class="size-3"
              >
                <path
                  d="M13.488 2.513a1.75 1.75 0 0 0-2.475 0L6.75 6.774a2.75 2.75 0 0 0-.596.892l-.848 2.047a.75.75 0 0 0 .98.98l2.047-.848a2.75 2.75 0 0 0 .892-.596l4.261-4.262a1.75 1.75 0 0 0 0-2.474Z"
                />
                <path
                  d="M4.75 3.5c-.69 0-1.25.56-1.25 1.25v6.5c0 .69.56 1.25 1.25 1.25h6.5c.69 0 1.25-.56 1.25-1.25V9A.75.75 0 0 1 14 9v2.25A2.75 2.75 0 0 1 11.25 14h-6.5A2.75 2.75 0 0 1 2 11.25v-6.5A2.75 2.75 0 0 1 4.75 2H7a.75.75 0 0 1 0 1.5H4.75Z"
                />
              </svg>
              {m.ai_builder_suggest_change()}
            </button>
          {/if}
        </Card.Content>
      </Collapsible.Content>
    </Card.Root>
  </Collapsible.Root>
</div>
