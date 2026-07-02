<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import FlowAIBuilderDiagnosticCopyButton from "./FlowAIBuilderDiagnosticCopyButton.svelte";
  import type { AIBuilderDiagnosticReport } from "./aiBuilderDiagnosticReport";
  import type { AIBuilderSuggestChangeIntent, StepChangeKind, StepSpec } from "./protocol";

  // Mirrors backend requires_completion_model: transcription uses flow config, not GPT.
  const TRANSCRIBE_ONLY_OUTPUT_MODE = "transcribe_only";

  interface Props {
    step: StepSpec;
    stepNumber: number;
    planId?: string | null;
    changeKind?: StepChangeKind;
    buildDiagnosticReport?: () => AIBuilderDiagnosticReport | null;
    isFirst?: boolean;
    isLast?: boolean;
    planStatus?: string;
    onsuggestchange?: (intent: AIBuilderSuggestChangeIntent) => void;
    resolveModelName?: (ref: string | null) => string | null;
    resolveMcpServerName?: (ref: string) => string | null;
    resolveMcpToolName?: (ref: string) => string | null;
  }

  let {
    step,
    stepNumber,
    planId = null,
    changeKind = step.existing_step_ref ? "unchanged" : "added",
    buildDiagnosticReport,
    isFirst = false,
    planStatus = "",
    onsuggestchange,
    resolveModelName,
    resolveMcpServerName,
    resolveMcpToolName
  }: Props = $props();

  let showDetails = $state(false);
  let instructionsExpanded = $state(false);

  type SchemaProperty = {
    type?: string;
    description?: string;
  };

  function schemaProperties(
    contract: Record<string, unknown> | null | undefined
  ): Record<string, SchemaProperty> {
    const properties = contract?.properties;
    if (!properties || typeof properties !== "object" || Array.isArray(properties)) return {};
    return properties as Record<string, SchemaProperty>;
  }

  const inputType = $derived(step.input_type ?? "text");
  const outputType = $derived(step.output_type ?? "text");
  const outputMode = $derived(step.output_mode ?? "pass_through");
  const usesFlowTranscriptionModel = $derived(outputMode === TRANSCRIBE_ONLY_OUTPUT_MODE);
  const knowledgeRefs = $derived(step.assistant_spec.knowledge_refs ?? []);
  const inputContractProperties = $derived(schemaProperties(step.input_contract));
  const outputContractProperties = $derived(schemaProperties(step.output_contract));

  const inputSourceLabel = $derived(
    (
      {
        flow_input: m.ai_builder_step_flow_input(),
        previous_step: m.ai_builder_step_previous_step(),
        all_previous_steps: m.ai_builder_step_all_previous()
      } as Record<string, string>
    )[step.input_source] ?? step.input_source
  );

  // Change affordance colors resolved once so markup stays clean.
  const indicatorClass = $derived(
    changeKind === "added"
      ? "bg-positive-dimmer text-positive-stronger"
      : changeKind === "modified"
        ? "bg-warning-dimmer text-warning-stronger"
        : "bg-secondary text-secondary"
  );

  const resolvedModel = $derived(
    !usesFlowTranscriptionModel && step.assistant_spec.model_ref
      ? (resolveModelName?.(step.assistant_spec.model_ref) ?? step.assistant_spec.model_ref)
      : null
  );

  const hasBindings = $derived(
    !!step.input_bindings && Object.keys(step.input_bindings).length > 0
  );
  const hasInputContract = $derived(Object.keys(inputContractProperties).length > 0);
  const hasOutputContract = $derived(Object.keys(outputContractProperties).length > 0);
  const hasInstructions = $derived(!!step.assistant_spec.instructions?.trim());
  const hasKnowledge = $derived(knowledgeRefs.length > 0);
  const mcpServerRefs = $derived(step.assistant_spec.mcp_server_refs ?? []);
  const mcpToolRefs = $derived(step.assistant_spec.mcp_tool_refs ?? []);
  const hasMcp = $derived(mcpServerRefs.length > 0 || mcpToolRefs.length > 0);
  const hasDiagnosticCopy = $derived(planStatus === "proposed" && !!buildDiagnosticReport);
  const hasAnyDetails = $derived(
    hasInstructions ||
      resolvedModel ||
      usesFlowTranscriptionModel ||
      hasKnowledge ||
      hasMcp ||
      hasBindings ||
      hasInputContract ||
      hasOutputContract ||
      hasDiagnosticCopy
  );

  function mcpServerLabel(ref: string): string {
    return resolveMcpServerName?.(ref) ?? ref;
  }

  function mcpToolLabel(ref: string): string {
    return resolveMcpToolName?.(ref) ?? ref;
  }

  function requestStepChange() {
    if (!planId) return;
    onsuggestchange?.({
      placeholder: m.ai_builder_step_change_placeholder({
        step: stepNumber,
        name: step.name
      }),
      editContext: {
        scope: "step",
        plan_id: planId,
        target_plan_step_ref: step.plan_step_ref,
        target_existing_step_ref: step.existing_step_ref,
        target_step_name: step.name,
        target_step_number: stepNumber
      }
    });
  }
</script>

<div
  class="step-card-enter relative"
  style:animation-delay="{stepNumber * 50}ms"
  style:animation-fill-mode="both"
  class:mt-2={!isFirst}
>
  <Collapsible.Root bind:open={showDetails}>
    <div
      class="border-default bg-primary group/step ring-foreground/10 overflow-hidden rounded-xl ring-1 transition-[box-shadow,border-color] duration-200 ease-out
        {showDetails ? 'ring-accent-default/30 shadow-sm' : 'hover:border-stronger'}"
    >
      <Collapsible.Trigger
        class="hover:bg-hover-dimmer/40 aria-expanded:bg-secondary/30 focus-visible:ring-accent-default/30 flex w-full items-center gap-3 px-4 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
        aria-label={`${m.ai_builder_step_label({ step: stepNumber })}: ${step.name}${changeKind === "added" ? ` (${m.ai_builder_badge_new()})` : changeKind === "modified" ? ` (${m.ai_builder_badge_modified()})` : ""}`}
        aria-describedby="step-{stepNumber}-meta"
      >
        <!-- Index tile. Tint changes per status; no border-left stripe. -->
        <span
          class="flex size-8 shrink-0 items-center justify-center rounded-lg text-[0.8125rem] font-semibold tabular-nums {indicatorClass}"
          aria-hidden="true"
        >
          {stepNumber}
        </span>

        <div class="flex min-w-0 flex-1 flex-col gap-1">
          <div class="flex min-w-0 flex-wrap items-center gap-2">
            <span
              class="text-primary min-w-0 truncate text-[0.9375rem] font-semibold tracking-[-0.005em]"
            >
              {step.name}
            </span>

            {#if changeKind === "added"}
              <Badge
                variant="outline"
                class="border-positive-default/30 bg-positive-dimmer text-positive-stronger h-5 px-1.5 text-[10px] font-semibold tracking-wide uppercase"
              >
                {m.ai_builder_badge_new()}
              </Badge>
            {:else if changeKind === "modified"}
              <Badge
                variant="outline"
                class="border-warning-default/30 bg-warning-dimmer text-warning-stronger h-5 px-1.5 text-[10px] font-semibold tracking-wide uppercase"
              >
                {m.ai_builder_badge_modified()}
              </Badge>
            {/if}

            {#if hasMcp}
              <Badge
                variant="outline"
                class="bg-accent-default/6 border-accent-default/20 text-accent-stronger h-5 px-1.5 text-[10px] font-semibold tracking-wide uppercase"
              >
                {m.mcp()}
              </Badge>
            {/if}

            {#if resolvedModel}
              <span class="text-muted ml-auto hidden max-w-[10rem] truncate text-xs sm:inline">
                {resolvedModel}
              </span>
            {/if}
          </div>

          <!-- IO line. id references aria-describedby on trigger for screen-reader meta. -->
          <div
            id="step-{stepNumber}-meta"
            class="text-muted flex flex-wrap items-center gap-x-2 gap-y-1 text-xs"
          >
            <span class="inline-flex items-center gap-1">
              <span class="font-medium">{m.ai_builder_step_input()}</span>
              <span aria-hidden="true">·</span>
              <span class="text-secondary">{inputSourceLabel}</span>
              <span aria-hidden="true" class="opacity-50">→</span>
              <span class="text-secondary">{inputType}</span>
            </span>
            <span aria-hidden="true" class="opacity-40">•</span>
            <span class="inline-flex items-center gap-1">
              <span class="font-medium">{m.ai_builder_step_output()}</span>
              <span aria-hidden="true">·</span>
              <span class="text-secondary">{outputType}</span>
              {#if outputMode !== "pass_through"}
                <span class="opacity-60">({outputMode})</span>
              {/if}
            </span>
            {#if resolvedModel}
              <span class="sr-only">· {m.ai_builder_step_model()} {resolvedModel}</span>
            {/if}
          </div>
        </div>

        {#if hasAnyDetails}
          <svg
            xmlns="http://www.w3.org/2000/svg"
            viewBox="0 0 16 16"
            fill="currentColor"
            class="text-muted size-4 shrink-0 transition-transform duration-200 ease-out {showDetails
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
        {/if}
      </Collapsible.Trigger>

      {#if hasAnyDetails}
        <Collapsible.Content>
          <div class="border-default border-t">
            <div class="bg-secondary/25 flex flex-col gap-5 px-4 py-4 sm:px-5 sm:py-5">
              {#if hasInstructions}
                <section class="flex flex-col gap-2">
                  <h4 class="text-muted text-[11px] font-semibold tracking-[0.06em] uppercase">
                    {m.ai_builder_step_instructions()}
                  </h4>
                  <p
                    class="text-secondary max-w-[72ch] text-[13px] leading-relaxed whitespace-pre-wrap"
                    class:line-clamp-5={!instructionsExpanded &&
                      step.assistant_spec.instructions.length > 300}
                  >
                    {step.assistant_spec.instructions}
                  </p>
                  {#if step.assistant_spec.instructions.length > 300}
                    <button
                      type="button"
                      class="text-accent-default hover:text-accent-stronger self-start text-xs font-medium transition-colors hover:underline focus-visible:underline focus-visible:outline-none"
                      onclick={(e) => {
                        e.stopPropagation();
                        instructionsExpanded = !instructionsExpanded;
                      }}
                    >
                      {instructionsExpanded ? m.ai_builder_show_less() : m.ai_builder_show_more()}
                    </button>
                  {/if}
                </section>
              {/if}

              {#if resolvedModel || usesFlowTranscriptionModel || hasKnowledge || hasMcp}
                <section class="grid gap-x-6 gap-y-4 sm:grid-cols-2">
                  {#if resolvedModel}
                    <div class="flex flex-col gap-1">
                      <h4 class="text-muted text-[11px] font-semibold tracking-[0.06em] uppercase">
                        {m.ai_builder_step_model()}
                      </h4>
                      <p class="text-secondary text-[13px] leading-snug">{resolvedModel}</p>
                    </div>
                  {/if}
                  {#if usesFlowTranscriptionModel}
                    <div class="flex flex-col gap-1">
                      <h4 class="text-muted text-[11px] font-semibold tracking-[0.06em] uppercase">
                        {m.ai_builder_step_transcription_model()}
                      </h4>
                      <p class="text-secondary text-[13px] leading-snug">
                        {m.ai_builder_step_transcription_model_hint()}
                      </p>
                    </div>
                  {/if}
                  {#if hasKnowledge}
                    <div class="flex flex-col gap-1">
                      <h4 class="text-muted text-[11px] font-semibold tracking-[0.06em] uppercase">
                        {m.ai_builder_step_knowledge()}
                      </h4>
                      <p class="text-secondary text-[13px] leading-snug">
                        {knowledgeRefs.join(", ")}
                      </p>
                    </div>
                  {/if}
                  {#if hasMcp}
                    <div class="flex flex-col gap-2 sm:col-span-2">
                      <h4 class="text-muted text-[11px] font-semibold tracking-[0.06em] uppercase">
                        {m.ai_builder_step_mcp_tools()}
                      </h4>
                      <div class="flex flex-wrap gap-1.5">
                        {#if mcpToolRefs.length > 0}
                          {#each mcpToolRefs as ref (ref)}
                            <Badge
                              variant="outline"
                              class="bg-accent-default/6 border-accent-default/20 text-accent-stronger max-w-full px-2 py-0.5 text-[11px] font-medium"
                              title={ref}
                            >
                              <span class="truncate">{mcpToolLabel(ref)}</span>
                            </Badge>
                          {/each}
                        {:else}
                          {#each mcpServerRefs as ref (ref)}
                            <Badge
                              variant="outline"
                              class="bg-accent-default/6 border-accent-default/20 text-accent-stronger max-w-full px-2 py-0.5 text-[11px] font-medium"
                              title={ref}
                            >
                              <span class="truncate">{mcpServerLabel(ref)}</span>
                            </Badge>
                          {/each}
                        {/if}
                      </div>
                      <p class="text-muted text-xs leading-snug">
                        {m.ai_builder_step_mcp_tools_hint()}
                      </p>
                    </div>
                  {/if}
                </section>
              {/if}

              {#if hasBindings}
                <section class="flex flex-col gap-2">
                  <h4 class="text-muted text-[11px] font-semibold tracking-[0.06em] uppercase">
                    {m.ai_builder_step_bindings()}
                  </h4>
                  <pre
                    class="border-default bg-primary text-secondary max-h-64 overflow-auto rounded-md border px-3 py-2 font-mono text-[11.5px] leading-relaxed break-words whitespace-pre-wrap">{JSON.stringify(
                      step.input_bindings,
                      null,
                      2
                    )}</pre>
                </section>
              {/if}

              {#if hasOutputContract}
                <section class="flex flex-col gap-2">
                  <h4 class="text-muted text-[11px] font-semibold tracking-[0.06em] uppercase">
                    {m.ai_builder_step_output_contract()}
                  </h4>
                  <dl
                    class="border-default divide-default divide-y overflow-hidden rounded-md border"
                  >
                    {#each Object.entries(outputContractProperties) as [name, schema] (name)}
                      <div
                        class="bg-primary grid grid-cols-[auto_auto_1fr] items-baseline gap-x-3 px-3 py-2 text-[12.5px]"
                      >
                        <code class="text-primary font-semibold">{name}</code>
                        <Badge variant="outline" class="h-4 px-1.5 py-0 text-[10px] font-normal">
                          {schema.type ?? "object"}
                        </Badge>
                        {#if schema.description}
                          <span class="text-muted leading-snug">{schema.description}</span>
                        {/if}
                      </div>
                    {/each}
                  </dl>
                </section>
              {/if}

              {#if hasInputContract}
                <section class="flex flex-col gap-2">
                  <h4 class="text-muted text-[11px] font-semibold tracking-[0.06em] uppercase">
                    {m.ai_builder_step_input_contract()}
                  </h4>
                  <dl
                    class="border-default divide-default divide-y overflow-hidden rounded-md border"
                  >
                    {#each Object.entries(inputContractProperties) as [name, schema] (name)}
                      <div
                        class="bg-primary grid grid-cols-[auto_auto_1fr] items-baseline gap-x-3 px-3 py-2 text-[12.5px]"
                      >
                        <code class="text-primary font-semibold">{name}</code>
                        <Badge variant="outline" class="h-4 px-1.5 py-0 text-[10px] font-normal">
                          {schema.type ?? "object"}
                        </Badge>
                        {#if schema.description}
                          <span class="text-muted leading-snug">{schema.description}</span>
                        {/if}
                      </div>
                    {/each}
                  </dl>
                </section>
              {/if}

              {#if planStatus === "proposed"}
                <div class="flex flex-wrap gap-2">
                  <button
                    type="button"
                    class="border-default text-secondary hover:border-accent-default/40 hover:text-accent-default focus-visible:ring-accent-default/30 inline-flex min-h-10 w-fit items-center gap-1.5 rounded-md border bg-transparent px-3 py-2 text-[0.8125rem] font-medium transition-colors focus-visible:ring-2 focus-visible:outline-none max-sm:w-full max-sm:justify-center sm:min-h-8 sm:px-2.5 sm:py-1.5 sm:text-xs"
                    onclick={(e) => {
                      e.stopPropagation();
                      requestStepChange();
                    }}
                  >
                    <svg
                      xmlns="http://www.w3.org/2000/svg"
                      viewBox="0 0 16 16"
                      fill="currentColor"
                      class="size-3"
                      aria-hidden="true"
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
                  <FlowAIBuilderDiagnosticCopyButton buildReport={buildDiagnosticReport} />
                </div>
              {/if}
            </div>
          </div>
        </Collapsible.Content>
      {/if}
    </div>
  </Collapsible.Root>
</div>

<style lang="postcss">
  @reference "@eneo/ui/styles";

  /* Subtle staggered entrance. No bounce; eased out like Linear's list reveals. */
  .step-card-enter {
    animation: step-card-enter 0.35s cubic-bezier(0.16, 1, 0.3, 1);
  }

  @keyframes step-card-enter {
    from {
      opacity: 0;
      transform: translateY(0.5rem);
    }
    to {
      opacity: 1;
      transform: translateY(0);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .step-card-enter {
      animation: none;
    }
  }
</style>
