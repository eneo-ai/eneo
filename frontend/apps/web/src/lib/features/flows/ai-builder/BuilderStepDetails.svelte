<script module lang="ts">
  import type { StepFieldChange } from "./protocol";

  /** One changed field with both values already in the plan's vocabulary. */
  export interface StepFieldChangeDisplay {
    field: StepFieldChange["field"];
    label: string;
    previous: string;
    current: string;
    /** The complete value of a structured field, canonical JSON; null for plain values. */
    previousDetail?: string | null;
    currentDetail?: string | null;
    /** The raw values behind `previous` and `current`, for readings that need them. */
    previousValue?: string | null;
    currentValue?: string | null;
  }
</script>

<script lang="ts">
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { m } from "$lib/paraglide/messages";
  import * as Collapsible from "$lib/components/ui/collapsible/index.js";
  import IconChevronDown from "@lucide/svelte/icons/chevron-down";
  import FlowAIBuilderDiagnosticCopyButton from "./FlowAIBuilderDiagnosticCopyButton.svelte";
  import BuilderStepChangeSummary from "./BuilderStepChangeSummary.svelte";
  import { getLocale } from "$lib/paraglide/runtime";
  import { contractFields, fieldLabel, readsLabel } from "./builderStepPhrases";
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
    /** "Läser steg 1 · Svarar med löpande text": the line the diagram node shows. */
    detail: string;
    modelLabel: string;
    /** The model is a plan fact here; it is changed in the step editor. */
    modelIsFixedHere?: boolean;
    /** "changes" marks an edit's changed step; "updated" a create plan's revised one. */
    changeBadge?: "new" | "updated" | "changes" | null;
    /** An unchanged step in an edit: its number stays neutral so the change stands out. */
    quiet?: boolean;
    /** The review's main card: the body alone, framed and titled by the review. */
    featured?: boolean;
    /** What the proposal changes in this published step (edit mode). */
    fieldChanges?: StepFieldChangeDisplay[];
    pausesForReview?: boolean;
    perFile?: boolean;
    canRequestChange?: boolean;
    buildDiagnosticReport?: () => AIBuilderDiagnosticReport | null;
    resolveInputStepLabel?: (ref: string) => string | null;
    /** The 1-based position of a planned step, for "Läser steg 1 och 2". */
    resolveStepNumber?: (ref: string) => number | null;
    onrequestchange?: () => void;
  }

  let {
    step,
    stepNumber,
    open = false,
    onopenchange,
    detail,
    modelLabel,
    modelIsFixedHere = true,
    changeBadge = null,
    quiet = false,
    featured = false,
    fieldChanges = [],
    pausesForReview = false,
    perFile = false,
    canRequestChange = false,
    buildDiagnosticReport,
    resolveInputStepLabel,
    resolveStepNumber = () => null,
    onrequestchange
  }: Props = $props();

  let wholeStepOpen = $state(false);

  const INSTRUCTION_CLAMP_CHARS = 300;

  let instructionsExpanded = $state(false);

  const outputFields = $derived(contractFields(step.output_contract));
  const inputFields = $derived(contractFields(step.input_contract));
  const knowledgeRefs = $derived(step.assistant_spec.knowledge_refs ?? []);
  const instructions = $derived(step.assistant_spec.instructions ?? "");
  const hasBindings = $derived(
    !!step.input_bindings && Object.keys(step.input_bindings).length > 0
  );
  const inputBindingsState = $derived(parseFlowInputBindings(step.input_bindings));

  const sourceLabel = $derived(readsLabel(step, stepNumber, resolveStepNumber));

  // The plan names its steps by stable keys ("step_a"); the reader knows them
  // by number and name, so a token that points at a planned step reads as it.
  // Only the key is replaced: any path past the step's text answer stays, so
  // two fields of one step never read alike.
  const TEMPLATE_TOKEN = /\{\{\s*([^{}]+?)\s*\}\}/g;
  function readableParts(text: string): { text: string; step: string | null }[] {
    const parts: { text: string; step: string | null }[] = [];
    let last = 0;
    for (const match of text.matchAll(TEMPLATE_TOKEN)) {
      const at = match.index;
      if (at > last) parts.push({ text: text.slice(last, at), step: null });
      const [stepRef, ...path] = match[1].split(".").map((segment) => segment.trim());
      const label = resolveInputStepLabel?.(stepRef) ?? null;
      const rest = path.join(".");
      const step =
        label === null || rest === "" || rest === "output.text" ? label : `${label} · ${rest}`;
      parts.push({ text: match[0], step });
      last = at + match[0].length;
    }
    if (last < text.length) parts.push({ text: text.slice(last), step: null });
    return parts;
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

{#snippet readableText(text: string)}
  {#each readableParts(text) as part, index (index)}
    {#if part.step}
      <Badge variant="secondary" class="max-w-full align-middle" title={part.text}>
        <span class="truncate">{part.step}</span>
      </Badge>
    {:else}
      {part.text}
    {/if}
  {/each}
{/snippet}

{#snippet facts()}
  {#if instructions.trim()}
    <h4 class="text-secondary mb-1 text-xs font-bold">
      {m.ai_builder_step_instructions()}
    </h4>
    <p
      class="text-primary max-w-[72ch] text-[0.8125rem] leading-relaxed whitespace-pre-wrap"
      class:line-clamp-5={!instructionsExpanded && instructions.length > INSTRUCTION_CLAMP_CHARS}
    >
      {@render readableText(instructions)}
    </p>
    {#if instructions.length > INSTRUCTION_CLAMP_CHARS}
      <Button
        variant="link"
        size="xs"
        class="text-accent-stronger mt-1 h-auto p-0 text-xs font-medium"
        onclick={() => (instructionsExpanded = !instructionsExpanded)}
      >
        {instructionsExpanded ? m.ai_builder_show_less() : m.ai_builder_show_more()}
      </Button>
    {/if}
  {/if}

  <div class="mt-3.5 flex flex-wrap gap-x-8 gap-y-3">
    <div>
      <h4 class="text-secondary mb-0.5 text-xs font-bold">{m.ai_builder_step_model()}</h4>
      <div class="text-primary text-[0.8125rem] font-semibold">{modelLabel}</div>
      {#if modelIsFixedHere}
        <div class="text-secondary text-xs">
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
                {@render readableText(inputBindingsState.question)}
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

  {#if outputFields.length > 0}
    <div class="mt-3.5">
      <h4 class="text-secondary mb-1.5 text-xs font-bold">
        {m.ai_builder_step_output_fields()}
      </h4>
      <div
        class="border-dimmer bg-primary divide-dimmer divide-y overflow-hidden rounded-[9px] border"
      >
        {#each outputFields as [name, schema] (name)}
          <div class="grid gap-x-3.5 px-3 py-2.5 sm:grid-cols-[13.125rem_1fr]">
            <div class="min-w-0">
              <div class="text-primary text-[0.8125rem] font-semibold text-pretty">
                {fieldLabel(name, schema, getLocale())}
              </div>
              <div class="text-secondary truncate font-mono text-xs">{name}</div>
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

  {#if inputFields.length > 0}
    <div class="mt-3.5">
      <h4 class="text-secondary mb-1.5 text-xs font-bold">
        {m.ai_builder_step_input_contract()}
      </h4>
      <div
        class="border-dimmer bg-primary divide-dimmer divide-y overflow-hidden rounded-[9px] border"
      >
        {#each inputFields as [name, schema] (name)}
          <div class="grid gap-x-3.5 px-3 py-2.5 sm:grid-cols-[13.125rem_1fr]">
            <div class="min-w-0">
              <div class="text-primary text-[0.8125rem] font-semibold text-pretty">
                {fieldLabel(name, schema, getLocale())}
              </div>
              <div class="text-secondary truncate font-mono text-xs">{name}</div>
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
{/snippet}

{#snippet actions()}
  {#if canRequestChange || buildDiagnosticReport}
    <div class="mt-3.5 flex flex-wrap gap-2">
      {#if canRequestChange}
        <Button
          variant="outline"
          size="sm"
          class="max-sm:h-11 max-sm:w-full"
          onclick={onrequestchange}
        >
          {m.ai_builder_step_request_change({ step: stepNumber })}
        </Button>
      {/if}
      <FlowAIBuilderDiagnosticCopyButton
        buildReport={buildDiagnosticReport}
        size="xs"
        variant="outline"
      />
    </div>
  {/if}
{/snippet}

{#snippet body()}
  {#if fieldChanges.length > 0}
    <BuilderStepChangeSummary
      {step}
      {stepNumber}
      changes={fieldChanges}
      stepNumberOf={resolveStepNumber}
      readable={readableText}
    />
    <!-- The change leads; the step's full facts wait one click away. -->
    <Collapsible.Root bind:open={wholeStepOpen} class="border-dimmer mt-6 border-t pt-3">
      <Collapsible.Trigger
        class="text-accent-stronger focus-visible:ring-accent-stronger rounded-sm text-xs font-medium underline underline-offset-2 focus-visible:ring-2 focus-visible:outline-none"
      >
        {wholeStepOpen
          ? m.ai_builder_change_hide_whole_step()
          : m.ai_builder_change_show_whole_step()}
      </Collapsible.Trigger>
      <Collapsible.Content class="collapsible-animate">
        <div class="pt-3">{@render facts()}</div>
      </Collapsible.Content>
    </Collapsible.Root>
  {:else}
    {@render facts()}
  {/if}
  <!-- The featured step's page already ends in its own change box. -->
  {#if !featured}
    {@render actions()}
  {/if}
{/snippet}

{#if featured}
  <div class="flex flex-col">{@render body()}</div>
{:else}
  <Collapsible.Root {open} onOpenChange={onopenchange}>
    <div
      class="bg-primary overflow-hidden rounded-[10px] border transition-colors {open
        ? 'border-stronger'
        : 'border-default'}"
    >
      <Collapsible.Trigger
        class="hover:bg-secondary focus-visible:ring-accent-stronger flex w-full items-center gap-3 px-3.5 py-3 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none"
      >
        <span
          class="inline-flex size-[1.625rem] shrink-0 items-center justify-center rounded-md text-xs font-bold tabular-nums
            {pausesForReview
            ? 'bg-warning-dimmer text-warning-stronger'
            : quiet
              ? 'bg-secondary text-secondary'
              : 'bg-accent-dimmer text-accent-stronger'}"
        >
          <span class="sr-only">{m.ai_builder_step_label({ step: stepNumber })}</span>
          <span aria-hidden="true">{stepNumber}</span>
        </span>
        <span class="flex min-w-0 flex-1 flex-col gap-0.5">
          <span class="flex flex-wrap items-center gap-1.5">
            <span class="text-primary text-[0.9375rem] font-semibold tracking-[-0.01em]">
              {step.name}
            </span>
            {#if pausesForReview}
              <span
                class="bg-warning-dimmer text-warning-stronger inline-flex h-[1.3125rem] items-center rounded-full px-2 text-xs font-semibold"
              >
                {m.ai_builder_node_review_checkpoint()}
              </span>
            {/if}
            {#if perFile}
              <span
                class="bg-secondary text-secondary inline-flex h-[1.3125rem] items-center rounded-full px-2 text-xs font-medium"
              >
                {m.ai_builder_node_per_file()}
              </span>
            {/if}
            {#if changeBadge}
              <span
                class="inline-flex h-[1.3125rem] items-center rounded-full px-2 text-xs font-semibold
                  {changeBadge === 'new'
                  ? 'bg-positive-dimmer text-positive-stronger'
                  : 'bg-accent-dimmer text-accent-stronger'}"
              >
                {changeBadge === "new"
                  ? m.ai_builder_badge_new()
                  : changeBadge === "changes"
                    ? m.ai_builder_node_changes()
                    : m.ai_builder_node_updated()}
              </span>
            {/if}
          </span>
          <span class="text-secondary text-xs">{detail}</span>
        </span>
        <IconChevronDown
          class="text-secondary size-4 shrink-0 motion-safe:transition-transform motion-safe:duration-(--duration-fast) motion-safe:ease-(--ease-smooth-out) {open
            ? 'rotate-180'
            : ''}"
          aria-hidden="true"
        />
      </Collapsible.Trigger>

      <Collapsible.Content class="collapsible-animate">
        <div class="border-dimmer border-t px-4 py-4">{@render body()}</div>
      </Collapsible.Content>
    </div>
  </Collapsible.Root>
{/if}
