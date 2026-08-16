<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import IconChevronDown from "@lucide/svelte/icons/chevron-down";
  import FlowAIBuilderDiagnosticCopyButton from "./FlowAIBuilderDiagnosticCopyButton.svelte";
  import type { AIBuilderDiagnosticReport } from "./aiBuilderDiagnosticReport";
  import type { StepSpec } from "./protocol";
  import {
    parseFlowInputBindings,
    type FlowInputBindingSourceRef
  } from "$lib/features/flows/flowInputBindings";

  interface Props {
    step: StepSpec;
    stepNumber: number;
    open: boolean;
    onopenchange?: (open: boolean) => void;
    /** "Ljud → Text" — same line the diagram node shows. */
    ioLabel: string;
    modelLabel: string;
    /** The model is a plan fact here; it is changed in the step editor. */
    modelIsFixedHere?: boolean;
    changeBadge?: "new" | "updated" | null;
    pausesForReview?: boolean;
    perFile?: boolean;
    canRequestChange?: boolean;
    buildDiagnosticReport?: () => AIBuilderDiagnosticReport | null;
    resolveInputStepLabel?: (ref: string) => string | null;
    onrequestchange?: () => void;
  }

  let {
    step,
    stepNumber,
    open = false,
    onopenchange,
    ioLabel,
    modelLabel,
    modelIsFixedHere = true,
    changeBadge = null,
    pausesForReview = false,
    perFile = false,
    canRequestChange = false,
    buildDiagnosticReport,
    resolveInputStepLabel,
    onrequestchange
  }: Props = $props();

  const INSTRUCTION_CLAMP_CHARS = 300;

  let instructionsExpanded = $state(false);

  type SchemaProperty = { type?: string; title?: string; description?: string };

  function schemaProperties(
    contract: Record<string, unknown> | null | undefined
  ): Record<string, SchemaProperty> {
    const properties = contract?.properties;
    if (!properties || typeof properties !== "object" || Array.isArray(properties)) return {};
    return properties as Record<string, SchemaProperty>;
  }

  const outputContractProperties = $derived(schemaProperties(step.output_contract));
  const inputContractProperties = $derived(schemaProperties(step.input_contract));
  const hasOutputContract = $derived(Object.keys(outputContractProperties).length > 0);
  const hasInputContract = $derived(Object.keys(inputContractProperties).length > 0);
  const knowledgeRefs = $derived(step.assistant_spec.knowledge_refs ?? []);
  const instructions = $derived(step.assistant_spec.instructions ?? "");
  const hasBindings = $derived(
    !!step.input_bindings && Object.keys(step.input_bindings).length > 0
  );
  const inputBindingsState = $derived(parseFlowInputBindings(step.input_bindings));

  const sourceLabel = $derived(
    (
      {
        flow_input: m.ai_builder_step_flow_input(),
        previous_step: m.ai_builder_step_previous_step(),
        all_previous_steps: m.ai_builder_step_all_previous()
      } as Record<string, string>
    )[step.input_source] ?? step.input_source
  );

  // Technical field names stay visible, but the readable name leads. Backend
  // schemas may carry a title; otherwise the snake_case name is unwrapped.
  function fieldLabel(name: string, schema: SchemaProperty): string {
    const title = schema.title?.trim();
    if (title) return title;
    const words = name.replace(/[_-]+/g, " ").trim();
    return words.charAt(0).toUpperCase() + words.slice(1);
  }

  function inputMaterialSourceTitle(source: FlowInputBindingSourceRef): string {
    return resolveInputStepLabel?.(source.stepRef) ?? m.flow_input_material_unknown_source();
  }

  function inputMaterialSourceMeta(source: FlowInputBindingSourceRef): string {
    const parts: string[] = [
      source.output === "structured"
        ? m.flow_input_template_source_output_structured()
        : m.flow_input_template_source_output_text(),
      source.fieldPath
        ? m.flow_input_material_selected_field({ field: source.fieldPath })
        : m.flow_input_material_whole_result()
    ];
    if (source.label) parts.push(source.label);
    return parts.join(" · ");
  }
</script>

<Collapsible.Root {open} onOpenChange={onopenchange}>
  <div
    class="bg-primary overflow-hidden rounded-[10px] border transition-colors {open
      ? 'border-stronger'
      : 'border-default'}"
  >
    <Collapsible.Trigger
      class="hover:bg-secondary focus-visible:ring-accent-default/40 flex w-full items-center gap-3 px-3.5 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
      aria-label="{m.ai_builder_step_label({ step: stepNumber })}: {step.name}"
    >
      <span
        class="inline-flex size-[1.625rem] shrink-0 items-center justify-center rounded-[7px] text-xs font-bold tabular-nums
          {pausesForReview
          ? 'bg-warning-dimmer text-warning-stronger'
          : 'bg-accent-dimmer text-accent-stronger'}"
        aria-hidden="true"
      >
        {stepNumber}
      </span>
      <span class="flex min-w-0 flex-1 flex-col gap-0.5">
        <span class="flex flex-wrap items-center gap-1.5">
          <span class="text-primary text-[0.875rem] font-semibold tracking-[-0.01em]">
            {step.name}
          </span>
          {#if pausesForReview}
            <span
              class="bg-warning-dimmer text-warning-stronger inline-flex h-[1.3125rem] items-center rounded-full px-2 text-[0.6875rem] font-semibold"
            >
              {m.ai_builder_node_review_checkpoint()}
            </span>
          {/if}
          {#if perFile}
            <span
              class="bg-secondary text-secondary inline-flex h-[1.3125rem] items-center rounded-full px-2 text-[0.6875rem] font-medium"
            >
              {m.ai_builder_node_per_file()}
            </span>
          {/if}
          {#if changeBadge}
            <span
              class="inline-flex h-[1.3125rem] items-center rounded-full px-2 text-[0.6875rem] font-semibold
                {changeBadge === 'new'
                ? 'bg-positive-dimmer text-positive-stronger'
                : 'bg-accent-dimmer text-accent-stronger'}"
            >
              {changeBadge === "new" ? m.ai_builder_badge_new() : m.ai_builder_node_updated()}
            </span>
          {/if}
        </span>
        <span class="text-secondary text-xs">{ioLabel}</span>
      </span>
      <IconChevronDown
        class="text-secondary size-4 shrink-0 transition-transform duration-200 ease-out {open
          ? 'rotate-180'
          : ''}"
        aria-hidden="true"
      />
    </Collapsible.Trigger>

    <Collapsible.Content class="collapsible-animate">
      <div class="border-dimmer bg-secondary border-t px-3.5 py-3.5">
        {#if instructions.trim()}
          <h4 class="text-secondary mb-1 text-xs font-bold">
            {m.ai_builder_step_instructions()}
          </h4>
          <p
            class="text-primary max-w-[72ch] text-[0.8125rem] leading-relaxed whitespace-pre-wrap"
            class:line-clamp-5={!instructionsExpanded &&
              instructions.length > INSTRUCTION_CLAMP_CHARS}
          >
            {instructions}
          </p>
          {#if instructions.length > INSTRUCTION_CLAMP_CHARS}
            <button
              type="button"
              class="text-accent-default hover:text-accent-stronger focus-visible:ring-accent-default/40 mt-1 rounded text-xs font-medium transition-colors hover:underline focus-visible:ring-2 focus-visible:outline-none"
              onclick={() => (instructionsExpanded = !instructionsExpanded)}
            >
              {instructionsExpanded ? m.ai_builder_show_less() : m.ai_builder_show_more()}
            </button>
          {/if}
        {/if}

        <div class="mt-3.5 flex flex-wrap gap-x-8 gap-y-3">
          <div>
            <h4 class="text-secondary mb-0.5 text-xs font-bold">{m.ai_builder_step_model()}</h4>
            <div class="text-primary text-[0.8125rem] font-semibold">{modelLabel}</div>
            {#if modelIsFixedHere}
              <div class="text-secondary text-[0.6875rem]">
                {m.ai_builder_step_model_changed_elsewhere()}
              </div>
            {/if}
          </div>
          <div>
            <h4 class="text-secondary mb-0.5 text-xs font-bold">{m.ai_builder_step_source()}</h4>
            <div class="text-primary text-[0.8125rem] font-semibold">{sourceLabel}</div>
          </div>
          {#if knowledgeRefs.length > 0}
            <div>
              <h4 class="text-secondary mb-0.5 text-xs font-bold">
                {m.ai_builder_step_knowledge()}
              </h4>
              <div class="text-primary text-[0.8125rem] font-semibold">
                {knowledgeRefs.join(", ")}
              </div>
            </div>
          {/if}
        </div>

        {#if hasBindings}
          <div class="mt-3.5">
            <h4 class="text-secondary mb-1.5 text-xs font-bold">{m.ai_builder_step_bindings()}</h4>
            {#if inputBindingsState.status === "invalid"}
              <p
                class="border-warning-default/40 bg-warning-dimmer text-warning-stronger rounded-md border px-3 py-2 text-xs leading-relaxed"
              >
                {m.flow_input_material_invalid_notice()}
              </p>
            {:else}
              <ul
                class="border-dimmer divide-dimmer bg-primary flex flex-col divide-y overflow-hidden rounded-[9px] border"
              >
                {#if inputBindingsState.question}
                  <li class="px-3 py-2">
                    <p class="text-primary text-xs font-semibold">
                      {m.flow_input_material_custom_text()}
                    </p>
                    <p class="text-secondary mt-1 text-xs leading-relaxed whitespace-pre-wrap">
                      {inputBindingsState.question}
                    </p>
                  </li>
                {/if}
                {#each inputBindingsState.sourceRefs as source, index (index)}
                  <li class="px-3 py-2">
                    <p class="text-primary text-xs font-semibold">
                      {inputMaterialSourceTitle(source)}
                    </p>
                    <p class="text-secondary mt-1 text-xs leading-relaxed">
                      {inputMaterialSourceMeta(source)}
                    </p>
                    {#if source.itemTemplate}
                      <p class="text-secondary mt-1 text-xs leading-relaxed">
                        {step.output_mode === "compose_text"
                          ? m.flow_input_material_advanced_notice()
                          : m.flow_input_material_item_template_unsupported_notice()}
                      </p>
                    {/if}
                  </li>
                {/each}
              </ul>
            {/if}
          </div>
        {/if}

        {#if hasOutputContract}
          <div class="mt-3.5">
            <h4 class="text-secondary mb-1.5 text-xs font-bold">
              {m.ai_builder_step_output_fields()}
            </h4>
            <div
              class="border-dimmer bg-primary divide-dimmer divide-y overflow-hidden rounded-[9px] border"
            >
              {#each Object.entries(outputContractProperties) as [name, schema] (name)}
                <div class="grid gap-x-3.5 px-3 py-2.5 sm:grid-cols-[13.125rem_1fr]">
                  <div class="min-w-0">
                    <div class="text-primary text-[0.8125rem] font-semibold text-pretty">
                      {fieldLabel(name, schema)}
                    </div>
                    <div class="text-secondary truncate font-mono text-[0.6875rem]">{name}</div>
                  </div>
                  {#if schema.description}
                    <div class="text-secondary text-xs leading-relaxed text-pretty">
                      {schema.description}
                    </div>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
        {:else}
          <p class="text-secondary mt-3 text-xs">{m.ai_builder_step_no_output_fields()}</p>
        {/if}

        {#if hasInputContract}
          <div class="mt-3.5">
            <h4 class="text-secondary mb-1.5 text-xs font-bold">
              {m.ai_builder_step_input_contract()}
            </h4>
            <div
              class="border-dimmer bg-primary divide-dimmer divide-y overflow-hidden rounded-[9px] border"
            >
              {#each Object.entries(inputContractProperties) as [name, schema] (name)}
                <div class="grid gap-x-3.5 px-3 py-2.5 sm:grid-cols-[13.125rem_1fr]">
                  <div class="min-w-0">
                    <div class="text-primary text-[0.8125rem] font-semibold text-pretty">
                      {fieldLabel(name, schema)}
                    </div>
                    <div class="text-secondary truncate font-mono text-[0.6875rem]">{name}</div>
                  </div>
                  {#if schema.description}
                    <div class="text-secondary text-xs leading-relaxed text-pretty">
                      {schema.description}
                    </div>
                  {/if}
                </div>
              {/each}
            </div>
          </div>
        {/if}

        {#if canRequestChange || buildDiagnosticReport}
          <div class="mt-3.5 flex flex-wrap gap-2">
            {#if canRequestChange}
              <button
                type="button"
                class="border-default text-primary hover:bg-tertiary focus-visible:ring-accent-default/40 inline-flex h-8 items-center rounded-lg border px-2.5 text-xs font-semibold transition-colors focus-visible:ring-2 focus-visible:outline-none max-sm:h-11 max-sm:w-full max-sm:justify-center"
                onclick={onrequestchange}
              >
                {m.ai_builder_step_request_change({ step: stepNumber })}
              </button>
            {/if}
            <FlowAIBuilderDiagnosticCopyButton
              buildReport={buildDiagnosticReport}
              size="xs"
              variant="outline"
            />
          </div>
        {/if}
      </div>
    </Collapsible.Content>
  </div>
</Collapsible.Root>
