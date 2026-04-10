<script lang="ts">
  import type { FlowRunContractStepInput, UploadedFile } from "@intric/intric-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { IconCheck } from "@intric/icons/check";
  import { IconInfo } from "@intric/icons/info";
  import type { NormalizedFlowFormField } from "$lib/features/flows/flowFormSchema";
  import type { FlowRunBlocker, FlowRunReviewSummaryItem } from "$lib/features/flows/flowRunWizard";
  import type { FlowRunDialogLabels } from "./flowRunDialogLabels";

  let {
    runBlockers,
    reviewSummaryItems,
    completedFormFieldSummaries,
    inputText,
    showFreeformTextInput,
    reviewFileGroups,
    labels,
    onGoToPage
  }: {
    runBlockers: FlowRunBlocker[];
    reviewSummaryItems: FlowRunReviewSummaryItem[];
    completedFormFieldSummaries: Array<{ field: NormalizedFlowFormField; value: string }>;
    inputText: string;
    showFreeformTextInput: boolean;
    reviewFileGroups: Array<{ step: FlowRunContractStepInput; files: UploadedFile[] }>;
    labels: FlowRunDialogLabels;
    onGoToPage: (pageId: FlowRunBlocker["pageId"]) => void;
  } = $props();

  function getStepLabel(step: FlowRunContractStepInput): string {
    return step.label?.trim() || labels.unnamedStep(step.step_order);
  }

  function formatBytes(bytes: number): string {
    if (!Number.isFinite(bytes) || bytes <= 0) return "0 B";
    const units = ["B", "KB", "MB", "GB"];
    let value = bytes;
    let unitIndex = 0;
    while (value >= 1024 && unitIndex < units.length - 1) {
      value /= 1024;
      unitIndex += 1;
    }
    return `${value.toFixed(value >= 10 || unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`;
  }
</script>

<div class="flex flex-col gap-4">
  {#if reviewSummaryItems.length > 0}
    <div class="px-1 py-1">
      <h4 class="text-sm font-semibold" data-wizard-heading tabindex="-1">
        {labels.reviewSummaryTitle}
      </h4>
      <div class="mt-3 flex flex-wrap gap-2">
        {#each reviewSummaryItems as item (item.id)}
          <span
            class="border-positive-default/20 bg-positive-dimmer/30 text-positive-stronger inline-flex items-center gap-1.5 rounded-full border px-3 py-1.5 text-xs font-medium"
          >
            <IconCheck class="size-3.5 shrink-0" />
            {item.label}
          </span>
        {/each}
      </div>
    </div>
  {/if}

  {#if runBlockers.length > 0}
    <div
      class="border-warning-default/30 bg-warning-dimmer text-warning-stronger rounded-xl border px-4 py-4"
      role="status"
      aria-live="polite"
    >
      <p class="flex items-center gap-2 text-sm font-semibold">
        <IconInfo class="size-4 shrink-0" />
        {labels.runBlockersTitle}
      </p>
      <div class="mt-3 flex flex-col gap-2">
        {#each runBlockers as blocker (blocker.id)}
          <div class="bg-primary/70 rounded-lg px-3 py-3">
            <div class="flex flex-wrap items-center justify-between gap-3">
              <p class="text-sm">{blocker.title}</p>
              <Button variant="outline" size="sm" onclick={() => onGoToPage(blocker.pageId)}>
                {blocker.actionLabel}
              </Button>
            </div>
          </div>
        {/each}
      </div>
    </div>
  {:else}
    <div
      class="bg-positive-default/10 text-positive-stronger flex items-center gap-3 rounded-xl px-4 py-3.5 text-sm"
    >
      <div
        class="bg-positive-default/15 flex size-7 shrink-0 items-center justify-center rounded-full"
      >
        <IconCheck class="size-4 shrink-0" />
      </div>
      <span class="font-medium">{labels.reviewReady}</span>
    </div>
  {/if}

  {#if completedFormFieldSummaries.length > 0}
    <div class="px-1 py-1">
      <h4 class="text-sm font-semibold">{labels.reviewFieldsTitle}</h4>
      <div class="mt-3 grid gap-3 md:grid-cols-2">
        {#each completedFormFieldSummaries as item (item.field.name)}
          <div class="bg-secondary/20 rounded-lg px-3 py-3">
            <p class="text-muted text-xs font-medium tracking-[0.12em] uppercase">
              {item.field.name}
            </p>
            <p class="mt-1 text-sm leading-relaxed">{item.value}</p>
          </div>
        {/each}
      </div>
    </div>
  {/if}

  {#if showFreeformTextInput && inputText.trim().length > 0}
    <div class="px-1 py-1">
      <h4 class="text-sm font-semibold">{labels.reviewTextTitle}</h4>
      <pre
        class="bg-secondary/20 mt-3 overflow-x-auto rounded-lg px-3 py-3 text-sm whitespace-pre-wrap">
{inputText.trim()}</pre>
    </div>
  {/if}

  {#if reviewFileGroups.length > 0}
    <div class="border-default rounded-xl border px-4 py-4">
      <h4 class="text-sm font-semibold">{labels.reviewFilesTitle}</h4>
      <div class="mt-3 flex flex-col gap-3">
        {#each reviewFileGroups as group (group.step.step_id)}
          <div class="flex flex-col gap-1.5">
            <p class="text-muted text-xs font-medium tracking-wide uppercase">
              {labels.runtimeReviewStep(group.step.step_order, getStepLabel(group.step))}
            </p>
            {#each group.files as file (file.id)}
              <div
                class="bg-secondary/10 flex items-center justify-between gap-3 rounded-lg px-3 py-2.5 text-sm"
              >
                <span class="min-w-0 truncate">{file.name ?? file.id}</span>
                {#if file.size}
                  <span class="text-muted shrink-0 text-xs">{formatBytes(file.size)}</span>
                {/if}
              </div>
            {/each}
          </div>
        {/each}
      </div>
    </div>
  {/if}
</div>
