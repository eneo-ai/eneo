<script lang="ts">
  import type { FlowStep } from "@eneo/eneo-js";
  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import { Search } from "lucide-svelte";
  import { m } from "$lib/paraglide/messages";
  import {
    getRecommendedTemplates,
    filterTemplates,
    resolveTemplateSeed,
    type FlowStepTemplate
  } from "$lib/features/flows/flowStepTemplates";
  import type { FlowStepCreationSeed } from "$lib/features/flows/FlowEditor";
  import { getInputTypeLabel, getOutputTypeLabel } from "./flowStepEditHelpers";
  import { cn } from "$lib/utils.js";

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

  function ioLabel(template: FlowStepTemplate): string {
    if (template.id === "document") {
      return `${getInputTypeLabel(template.displayInputType)} → ${documentFormat === "pdf" ? "PDF" : "Word"}`;
    }
    return `${getInputTypeLabel(template.displayInputType)} → ${getOutputTypeLabel(template.outputType)}`;
  }

  function confirmTemplate(template: FlowStepTemplate) {
    onConfirm(resolveTemplateSeed(template, documentFormat));
    open = false;
  }

  // Keyboard flow: Enter selects the only visible result, or confirms the
  // current selection (command-palette style).
  function handleSearchKeydown(event: KeyboardEvent) {
    if (event.key !== "Enter") return;
    const visible = [...recommended, ...more];
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
  <button
    type="button"
    aria-pressed={selectedId === template.id}
    class={cn(
      "border-default hover:bg-hover-dimmer/40 focus-visible:ring-accent-default/40 flex w-full items-center gap-3 rounded-xl border px-3 py-2.5 text-left transition-colors focus-visible:ring-2 focus-visible:outline-none",
      selectedId === template.id && "border-accent-default/50 bg-accent-dimmer/40"
    )}
    onclick={() => (selectedId = template.id)}
    ondblclick={() => confirmTemplate(template)}
  >
    <span
      class="bg-secondary/40 text-secondary flex size-9 shrink-0 items-center justify-center rounded-lg"
      aria-hidden="true"
    >
      <Icon class="size-4" />
    </span>
    <span class="min-w-0 flex-1">
      <span class="text-primary block truncate text-sm font-medium">{template.name()}</span>
      <span class="text-muted block truncate text-xs">{template.description()}</span>
    </span>
    {#if !template.blank}
      <span class="text-muted shrink-0 text-xs" style="font-variant-numeric: tabular-nums">
        {ioLabel(template)}
      </span>
    {/if}
  </button>
{/snippet}

<Dialog.Root bind:open>
  <Dialog.Content class="sm:max-w-lg">
    <Dialog.Header>
      <Dialog.Title>{m.flow_step_add()}</Dialog.Title>
      <Dialog.Description>{m.flow_add_step_subtitle()}</Dialog.Description>
    </Dialog.Header>

    <div class="relative">
      <Search
        class="text-muted pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
        aria-hidden="true"
      />
      <Input
        bind:value={query}
        placeholder={m.flow_add_step_search()}
        class="focus-visible:ring-accent-default/40 pl-9 focus-visible:ring-2"
        aria-label={m.flow_add_step_search()}
        name="flow-template-search"
        autocomplete="off"
        onkeydown={handleSearchKeydown}
      />
    </div>

    <div class="flex flex-col gap-4 overflow-y-auto py-1" style="max-height: 52vh">
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
        <p class="text-muted px-1 py-6 text-center text-sm">{m.flow_add_step_no_results()}</p>
      {/if}
    </div>

    <Dialog.Footer class="border-default">
      {#if selectedTemplate?.id === "document"}
        <div class="mr-auto flex items-center gap-2">
          <span class="text-secondary text-xs font-medium">{m.flow_add_step_format()}</span>
          <div class="flex gap-1">
            <button
              type="button"
              aria-pressed={documentFormat === "docx"}
              class={cn(
                "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                documentFormat === "docx"
                  ? "border-accent-default/50 bg-accent-dimmer/50 text-accent-stronger"
                  : "border-default text-secondary hover:bg-hover-dimmer/40"
              )}
              onclick={() => (documentFormatOverride = "docx")}
            >
              {m.flow_add_step_format_word()}
            </button>
            <button
              type="button"
              aria-pressed={documentFormat === "pdf"}
              class={cn(
                "rounded-md border px-2.5 py-1 text-xs font-medium transition-colors",
                documentFormat === "pdf"
                  ? "border-accent-default/50 bg-accent-dimmer/50 text-accent-stronger"
                  : "border-default text-secondary hover:bg-hover-dimmer/40"
              )}
              onclick={() => (documentFormatOverride = "pdf")}
            >
              {m.flow_add_step_format_pdf()}
            </button>
          </div>
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
