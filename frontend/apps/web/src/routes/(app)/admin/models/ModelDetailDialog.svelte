<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Read-only detail view of a single model. Reached by clicking a model row
  in the admin table. Edit + migrate actions hand off to dedicated dialogs.
-->

<script lang="ts">
  import { onMount } from "svelte";
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@eneo/eneo-js";
  import { writable, type Writable } from "svelte/store";
  import { m } from "$lib/paraglide/messages";
  import { Pencil, TriangleAlert, Clock, ArrowRight, ExternalLink } from "lucide-svelte";

  import * as Dialog from "$lib/components/ui/dialog/index.js";
  import * as Tabs from "$lib/components/ui/tabs/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

  import EditModelDialog from "./EditModelDialog.svelte";
  import MigrateModelDialog from "./MigrateModelDialog.svelte";
  import ModelUsageSection from "./ModelUsageSection.svelte";
  import { formatTokens, getDeprecationStatus } from "$lib/features/ai-models/formatModelStats";
  import { findHostingLabel } from "$lib/features/ai-models/hosting/hostingOptions";
  import ModelCostBadge from "$lib/features/ai-models/components/ModelCostBadge.svelte";

  let {
    openController,
    model,
    type,
    completionModels = []
  }: {
    openController: Writable<boolean>;
    model: CompletionModel | EmbeddingModel | TranscriptionModel;
    type: "completionModel" | "embeddingModel" | "transcriptionModel";
    completionModels?: CompletionModel[];
  } = $props();

  // Bridge the legacy Writable<boolean> contract to runes so shadcn Dialog's
  // bind:open works. Same pattern as AddWizard / EditModelDialog.
  let dialogOpen = $state(false);
  onMount(() => openController.subscribe((value) => (dialogOpen = value)));
  $effect(() => {
    openController.set(dialogOpen);
  });

  const showEditDialog = writable(false);
  const showMigrateDialog = writable(false);

  // Usage tab exists for completion + transcription (both expose usage
  // endpoints); embedding models have none. It lazy-loads on activation, so
  // it must not be the default tab.
  let activeTab = $state("info");
  const showUsageTab = $derived(type === "completionModel" || type === "transcriptionModel");

  const deprecation = $derived(
    getDeprecationStatus("deprecation_date" in model ? model : { deprecation_date: null })
  );
  const isMigratedCompletionModel = $derived(
    type === "completionModel" && "migrated_to_model_id" in model && !!model.migrated_to_model_id
  );

  function openEdit() {
    dialogOpen = false;
    showEditDialog.set(true);
  }
  function openMigrate() {
    dialogOpen = false;
    showMigrateDialog.set(true);
  }
</script>

<Dialog.Root bind:open={dialogOpen}>
  <Dialog.Content class="flex max-h-[90vh] flex-col gap-0 p-0 sm:max-w-3xl">
    <Dialog.Header class="px-6 pt-6 pb-2">
      <Dialog.Title>{model.nickname ?? model.name}</Dialog.Title>
    </Dialog.Header>

    <div class="min-h-0 flex-1 overflow-y-auto">
      <!-- Deprecation banner -->
      {#if deprecation.kind === "deprecated"}
        <div
          class="border-negative-default/20 bg-negative-dimmer/40 text-negative-stronger flex items-center justify-between gap-6 border-b px-6 py-4"
          role="alert"
        >
          <div class="flex items-center gap-3 text-base">
            <TriangleAlert size={20} class="flex-shrink-0" aria-hidden="true" />
            <span>{m.model_tooltip_deprecated({ date: deprecation.date })}</span>
          </div>
          {#if type === "completionModel" && !isMigratedCompletionModel}
            <button
              type="button"
              class="border-negative-default/30 text-negative-stronger hover:bg-negative-dimmer inline-flex flex-shrink-0 items-center gap-2 rounded-md border px-4 py-2 text-sm font-medium transition-colors"
              onclick={openMigrate}
            >
              {m.migrate_model_usage()}
              <ArrowRight size={15} aria-hidden="true" />
            </button>
          {/if}
        </div>
      {:else if deprecation.kind === "retiring"}
        <div
          class="border-warning-default/20 bg-warning-dimmer/40 text-warning-stronger flex items-center gap-3 border-b px-6 py-4 text-base"
          role="alert"
        >
          <Clock size={20} class="flex-shrink-0" aria-hidden="true" />
          <span>{m.model_tooltip_retiring({ date: deprecation.date })}</span>
        </div>
      {/if}

      {#if showUsageTab}
        <Tabs.Root bind:value={activeTab}>
          <Tabs.List variant="line" class="w-full justify-start px-6 pt-2">
            <Tabs.Trigger value="info">{m.model_detail_tab_info()}</Tabs.Trigger>
            <Tabs.Trigger value="usage">{m.model_detail_tab_usage()}</Tabs.Trigger>
          </Tabs.List>
          <Tabs.Content value="info">{@render properties()}</Tabs.Content>
          <Tabs.Content value="usage">
            <div class="px-6 py-5">
              <ModelUsageSection
                type={type === "transcriptionModel" ? "transcriptionModel" : "completionModel"}
                modelId={model.id}
                active={activeTab === "usage"}
              />
            </div>
          </Tabs.Content>
        </Tabs.Root>
      {:else}
        {@render properties()}
      {/if}
    </div>

    <div class="border-border flex justify-end gap-2 border-t px-6 py-4">
      <Button variant="outline" onclick={() => (dialogOpen = false)}>{m.close()}</Button>
      <Button variant="outline" onclick={openEdit}>
        <Pencil class="size-4" aria-hidden="true" />
        {m.model_detail_edit()}
      </Button>
    </div>
  </Dialog.Content>
</Dialog.Root>

{#snippet properties()}
  <div class="px-6 py-5">
    <table class="w-full">
      <tbody class="text-[15px]">
        <tr>
          <td class="text-muted w-40 py-2.5 pr-8 align-top whitespace-nowrap">{m.display_name()}</td
          >
          <td class="py-2.5">{model.nickname ?? model.name}</td>
        </tr>
        <tr>
          <td class="text-muted w-40 py-2.5 pr-8 align-top whitespace-nowrap"
            >{m.model_identifier()}</td
          >
          <td class="py-2.5">{model.name}</td>
        </tr>

        <!-- Context window -->
        {#if "max_input_tokens" in model}
          <tr>
            <td class="text-muted py-2.5 pr-8 align-top whitespace-nowrap"
              >{m.model_context_label()}</td
            >
            <td class="py-2.5 font-mono text-sm">
              {m.model_context_value({
                input: formatTokens(model.max_input_tokens),
                output: formatTokens(model.max_output_tokens)
              })}
            </td>
          </tr>
        {/if}

        <!-- Capabilities -->
        {#if "reasoning" in model}
          <tr>
            <td class="text-muted py-2.5 pr-8 align-top whitespace-nowrap"
              >{m.capability_reasoning()}</td
            >
            <td class="py-2.5">
              {#if model.reasoning}
                <span class="text-positive-default text-lg" aria-hidden="true">✓</span>
                <span class="sr-only">{m.yes()}</span>
              {:else}
                <span class="text-muted/30">–</span>
              {/if}
            </td>
          </tr>
        {/if}
        {#if "vision" in model}
          <tr>
            <td class="text-muted py-2.5 pr-8 align-top whitespace-nowrap"
              >{m.capability_vision()}</td
            >
            <td class="py-2.5">
              {#if model.vision}
                <span class="text-positive-default text-lg" aria-hidden="true">✓</span>
                <span class="sr-only">{m.yes()}</span>
              {:else}
                <span class="text-muted/30">–</span>
              {/if}
            </td>
          </tr>
        {/if}
        {#if "supports_tool_calling" in model}
          <tr>
            <td class="text-muted py-2.5 pr-8 align-top whitespace-nowrap"
              >{m.capability_tools()}</td
            >
            <td class="py-2.5">
              {#if model.supports_tool_calling}
                <span class="text-positive-default text-lg" aria-hidden="true">✓</span>
                <span class="sr-only">{m.yes()}</span>
              {:else}
                <span class="text-muted/30">–</span>
              {/if}
            </td>
          </tr>
        {/if}

        <tr>
          <td colspan="2" class="py-2"><div class="border-dimmer border-t"></div></td>
        </tr>

        <!-- Hosting -->
        {#if model.hosting}
          <tr>
            <td class="text-muted py-2.5 pr-8 align-top whitespace-nowrap">{m.hosting_region()}</td>
            <td class="py-2.5">{findHostingLabel(model.hosting) || model.hosting.toUpperCase()}</td>
          </tr>
        {/if}

        <!-- Indicative cost -->
        <tr>
          <td class="text-muted py-2.5 pr-8 align-top whitespace-nowrap"
            >{m.model_pricing_label()}</td
          >
          <td class="py-2.5">
            <ModelCostBadge {model} />
          </td>
        </tr>

        <!-- Security classification (read-only) -->
        <tr>
          <td class="text-muted py-2.5 pr-8 align-top whitespace-nowrap">{m.security()}</td>
          <td class="py-2.5">
            {#if model.security_classification}
              {model.security_classification.name}
            {:else}
              <span class="text-muted/30">{m.no_classification()}</span>
            {/if}
          </td>
        </tr>

        <!-- Open source -->
        {#if model.open_source}
          <tr>
            <td class="text-muted py-2.5 pr-8 align-top whitespace-nowrap"
              >{m.model_label_open_source()}</td
            >
            <td class="py-2.5">
              <span class="text-positive-default text-lg" aria-hidden="true">✓</span>
              <span class="sr-only">{m.yes()}</span>
            </td>
          </tr>
        {/if}

        <!-- Metadata divider only if at least one of the metadata rows below renders -->
        {#if model.family || model.org || model.description}
          <tr>
            <td colspan="2" class="py-2"><div class="border-dimmer border-t"></div></td>
          </tr>
        {/if}

        {#if model.family}
          <tr>
            <td class="text-muted py-2.5 pr-8 align-top whitespace-nowrap">{m.model_family()}</td>
            <td class="py-2.5">{model.family}</td>
          </tr>
        {/if}
        {#if model.org}
          <tr>
            <td class="text-muted py-2.5 pr-8 align-top whitespace-nowrap">{m.provider()}</td>
            <td class="py-2.5">{model.org}</td>
          </tr>
        {/if}
        {#if model.description}
          <tr>
            <td class="text-muted py-2.5 pr-8 align-top whitespace-nowrap">{m.description()}</td>
            <td class="text-muted py-2.5">{model.description}</td>
          </tr>
        {/if}
      </tbody>
    </table>

    {#if model.hf_link}
      <!-- eslint-disable svelte/no-navigation-without-resolve -- external HuggingFace URL from model metadata -->
      <a
        href={model.hf_link}
        target="_blank"
        rel="noopener noreferrer"
        class="text-accent-default mt-4 inline-flex items-center gap-1.5 text-sm hover:underline"
      >
        <!-- eslint-disable eneo/no-hardcoded-text -- HuggingFace is a brand name -->
        HuggingFace
        <!-- eslint-enable eneo/no-hardcoded-text -->
        <ExternalLink size={13} aria-hidden="true" />
      </a>
      <!-- eslint-enable svelte/no-navigation-without-resolve -->
    {/if}
  </div>
{/snippet}

<EditModelDialog {model} {type} openController={showEditDialog} />

{#if type === "completionModel" && !isMigratedCompletionModel}
  <MigrateModelDialog
    openController={showMigrateDialog}
    sourceModel={model as CompletionModel}
    models={completionModels}
  />
{/if}
