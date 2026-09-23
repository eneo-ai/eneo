<script lang="ts">
  import type { FlowStep } from "@eneo/eneo-js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import Search from "@lucide/svelte/icons/search";
  import { m } from "$lib/paraglide/messages";
  import {
    getRecommendedTemplates,
    filterTemplates,
    resolveTemplateSeed,
    type FlowStepTemplate
  } from "$lib/features/flows/flowStepTemplates";
  import type { FlowStepCreationSeed } from "$lib/features/flows/FlowEditor";
  import {
    getEnkelAwareOutputTypeLabel,
    getInputTypeLabel,
    getOutputTypeLabel
  } from "./flowStepEditHelpers";
  import { getFlowUserMode } from "$lib/features/flows/FlowUserMode";
  import * as RadioGroup from "$lib/components/ui/radio-group/index.js";
  import * as ToggleGroup from "$lib/components/ui/toggle-group/index.js";

  let {
    open = $bindable(false),
    previousOutputType,
    onConfirm
  }: {
    open?: boolean;
    previousOutputType: FlowStep["output_type"] | null;
    onConfirm: (seed: FlowStepCreationSeed | null) => void;
  } = $props();

  let selectedId = $state<string | null>(null);
  let query = $state("");
  let documentFormatOverride = $state<"docx" | "pdf" | null>(null);

  const partitions = $derived(getRecommendedTemplates(previousOutputType));
  const recommended = $derived(filterTemplates(partitions.recommended, query));
  const more = $derived(filterTemplates(partitions.more, query));
  const hasResults = $derived(recommended.length > 0 || more.length > 0);
  // Derive from the VISIBLE (filtered) rows so a selection hidden by search
  // can't be confirmed by the footer CTA.
  const selectedTemplate = $derived(
    [...recommended, ...more].find((t) => t.id === selectedId) ?? null
  );

  // The document template creates Word by default; a "pdf" search preselects
  // PDF, and the footer chips let the user set it explicitly before adding.
  const documentFormat = $derived<"docx" | "pdf">(
    documentFormatOverride ?? (/\bpdf\b/i.test(query) ? "pdf" : "docx")
  );

  const DOCUMENT_FORMATS = [
    { value: "docx", label: () => m.flow_add_step_format_word() },
    { value: "pdf", label: () => m.flow_add_step_format_pdf() }
  ] as const;

  const mode = getFlowUserMode();
  const isAdvancedMode = $derived($mode === "power_user");

  function ioLabel(template: FlowStepTemplate): string {
    if (template.id === "document") {
      return `${getInputTypeLabel(template.displayInputType)} → ${documentFormat === "pdf" ? "PDF" : "Word"}`;
    }
    const outputLabel = getEnkelAwareOutputTypeLabel(
      template.outputType,
      getOutputTypeLabel(template.outputType),
      isAdvancedMode
    );
    return `${getInputTypeLabel(template.displayInputType)} → ${outputLabel}`;
  }

  function confirmTemplate(template: FlowStepTemplate) {
    onConfirm(resolveTemplateSeed(template, documentFormat));
    open = false;
  }

  // Keyboard flow (command-palette style): arrows move the selection through
  // the visible rows, Enter confirms the selection or the only result.
  function handleSearchKeydown(event: KeyboardEvent) {
    const visible = [...recommended, ...more];
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      if (visible.length === 0) return;
      event.preventDefault();
      const index = visible.findIndex((t) => t.id === selectedId);
      const delta = event.key === "ArrowDown" ? 1 : -1;
      const next = visible[(index + delta + visible.length) % visible.length] ?? visible[0];
      selectedId = next.id;
      return;
    }
    if (event.key !== "Enter") return;
    if (selectedTemplate) {
      event.preventDefault();
      confirmTemplate(selectedTemplate);
    } else if (visible.length === 1) {
      event.preventDefault();
      selectedId = visible[0].id;
    }
  }

  // Start every open with a clean slate.
  $effect(() => {
    if (open) {
      selectedId = null;
      query = "";
      documentFormatOverride = null;
    }
  });
</script>

{#snippet templateRow(template: FlowStepTemplate)}
  {@const Icon = template.icon}
  {@const itemId = `flow-step-template-${template.id}`}
  <!-- DESIGN.md option row: the whole row labels its radio; a selected row
       gets the civic-blue border and inset ring over a 7% wash. The
       description is what helps someone choose, so it wraps. -->
  <label
    for={itemId}
    class="border-default hover:border-strongest hover:bg-secondary has-data-[state=checked]:border-accent-default has-data-[state=checked]:bg-accent-default/7 has-data-[state=checked]:ring-accent-default flex w-full cursor-pointer items-start gap-3 rounded-[10px] border p-3 transition-colors has-data-[state=checked]:ring-1 has-data-[state=checked]:ring-inset"
    ondblclick={() => confirmTemplate(template)}
  >
    <RadioGroup.Item id={itemId} value={template.id} class="mt-0.5" />
    <span class="min-w-0 flex-1">
      <span class="text-primary flex items-center gap-1.5 text-sm font-medium">
        <Icon class="text-secondary size-4 shrink-0" aria-hidden="true" />
        {template.name()}
      </span>
      <span class="text-secondary mt-0.5 block text-xs leading-relaxed text-pretty">
        {template.description()}
      </span>
    </span>
    {#if !template.blank}
      <span class="text-secondary shrink-0 text-xs whitespace-nowrap tabular-nums">
        {ioLabel(template)}
      </span>
    {/if}
  </label>
{/snippet}

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-xl">
    <Dialog.Header>
      <Dialog.Title>{m.flow_step_add()}</Dialog.Title>
      <Dialog.Description>{m.flow_add_step_subtitle()}</Dialog.Description>
    </Dialog.Header>

    <div class="relative">
      <Search
        class="text-secondary pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
        aria-hidden="true"
      />
      <Input
        bind:value={query}
        placeholder={m.flow_add_step_search()}
        class="focus-visible:ring-ring pl-9 focus-visible:ring-2"
        aria-label={m.flow_add_step_search()}
        name="flow-template-search"
        autocomplete="off"
        onkeydown={handleSearchKeydown}
      />
    </div>
    <div class="sr-only" role="status" aria-live="polite">
      {selectedTemplate ? selectedTemplate.name() : ""}
    </div>

    <RadioGroup.Root
      value={selectedId ?? ""}
      onValueChange={(value) => (selectedId = value || null)}
      aria-label={m.flow_add_step_templates_label()}
      class="flex flex-col gap-4 overflow-y-auto py-1"
      style="max-height: 52vh"
    >
      {#if recommended.length > 0}
        <div class="flex flex-col gap-1.5">
          <span class="text-secondary px-1 text-xs font-medium">
            {m.flow_add_step_recommended()}
          </span>
          {#each recommended as template (template.id)}
            {@render templateRow(template)}
          {/each}
        </div>
      {/if}

      {#if more.length > 0}
        <div class="flex flex-col gap-1.5">
          <span class="text-secondary px-1 text-xs font-medium">
            {m.flow_add_step_more()}
          </span>
          {#each more as template (template.id)}
            {@render templateRow(template)}
          {/each}
        </div>
      {/if}

      {#if !hasResults}
        <p class="text-secondary px-1 py-6 text-center text-sm">{m.flow_add_step_no_results()}</p>
      {/if}
    </RadioGroup.Root>

    <Dialog.Footer class="border-default">
      {#if selectedTemplate?.id === "document"}
        <div class="mr-auto flex items-center gap-2">
          <span class="text-secondary text-xs font-medium">{m.flow_add_step_format()}</span>
          <ToggleGroup.Root
            type="single"
            variant="outline"
            size="sm"
            spacing={0}
            value={documentFormat}
            onValueChange={(value) => {
              if (value === "docx" || value === "pdf") documentFormatOverride = value;
            }}
            aria-label={m.flow_add_step_format()}
          >
            {#each DOCUMENT_FORMATS as option (option.value)}
              <ToggleGroup.Item value={option.value}>{option.label()}</ToggleGroup.Item>
            {/each}
          </ToggleGroup.Root>
        </div>
      {/if}
      <Button variant="outline" onclick={() => (open = false)}>{m.cancel()}</Button>
      <Button
        disabled={!selectedTemplate}
        onclick={() => selectedTemplate && confirmTemplate(selectedTemplate)}
      >
        {m.flow_step_add()}
      </Button>
    </Dialog.Footer>
  </Dialog.Content>
</Dialog.Root>
