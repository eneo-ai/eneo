<script lang="ts">
  import type { FlowRunContractStepInput, UploadedFile } from "@intric/intric-js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Alert from "$lib/components/ui/alert/index.js";
  import { IconCheck } from "@intric/icons/check";
  import { IconInfo } from "@intric/icons/info";
  import { m } from "$lib/paraglide/messages";
  import type { FlowCareDataPolicy } from "$lib/features/flows/flowCareDataPolicy";
  import type { NormalizedFlowFormField } from "$lib/features/flows/flowFormSchema";
  import type { FlowRunBlocker, FlowRunReviewSummaryItem } from "$lib/features/flows/flowRunWizard";
  import type { FlowRunDialogLabels } from "./flowRunDialogLabels";

  let {
    runBlockers,
    reviewSummaryItems,
    completedFormFieldSummaries,
    careDataPolicy = undefined,
    inputText,
    showFreeformTextInput,
    reviewFileGroups,
    labels,
    onGoToPage
  }: {
    runBlockers: FlowRunBlocker[];
    reviewSummaryItems: FlowRunReviewSummaryItem[];
    completedFormFieldSummaries: Array<{ field: NormalizedFlowFormField; value: string }>;
    careDataPolicy?: FlowCareDataPolicy;
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

<div class="flex flex-col gap-5">
  {#if careDataPolicy?.sensitive && careDataPolicy.preApprovalVisibility === "uploader_and_reviewers"}
    <Alert.Root class="border-warning-default/30 bg-warning-dimmer text-warning-stronger">
      <IconInfo />
      <Alert.Title>{m.flow_sensitive_review_boundary_title()}</Alert.Title>
      <Alert.Description>{m.flow_sensitive_review_boundary_body()}</Alert.Description>
    </Alert.Root>
  {/if}

  {#if runBlockers.length > 0}
    <Alert.Root
      variant="destructive"
      class="border-warning-default/40 bg-warning-dimmer text-warning-stronger"
    >
      <IconInfo />
      <Alert.Title>{labels.runBlockersTitle}</Alert.Title>
      <Alert.Description>
        <ul class="mt-1 flex flex-col gap-2">
          {#each runBlockers as blocker (blocker.id)}
            <li class="flex flex-wrap items-center justify-between gap-3">
              <span class="text-sm">{blocker.title}</span>
              <Button
                variant="outline"
                size="sm"
                class="shrink-0"
                onclick={() => onGoToPage(blocker.pageId)}
              >
                {blocker.actionLabel}
              </Button>
            </li>
          {/each}
        </ul>
      </Alert.Description>
    </Alert.Root>
  {:else}
    <Alert.Root class="border-positive-default/30 bg-positive-dimmer/40 text-positive-stronger">
      <IconCheck />
      <Alert.Title class="font-medium">{labels.reviewReady}</Alert.Title>
    </Alert.Root>
  {/if}

  {#if reviewSummaryItems.length > 0}
    <section class="flex flex-col gap-2 px-1">
      <h4 class="text-primary text-sm font-semibold" data-wizard-heading tabindex="-1">
        {labels.reviewSummaryTitle}
      </h4>
      <div class="flex flex-wrap gap-2">
        {#each reviewSummaryItems as item (item.id)}
          <Badge variant="secondary" class="h-6 gap-1.5 px-2.5">
            <IconCheck class="size-3 shrink-0" />
            {item.label}
          </Badge>
        {/each}
      </div>
    </section>
  {/if}

  {#if completedFormFieldSummaries.length > 0}
    <section class="flex flex-col gap-3 px-1">
      <h4 class="text-primary text-sm font-semibold">{labels.reviewFieldsTitle}</h4>
      <dl class="grid gap-2 sm:grid-cols-2">
        {#each completedFormFieldSummaries as item (item.field.name)}
          <div class="border-default bg-secondary/25 rounded-lg border px-3 py-2.5">
            <dt class="text-muted text-[0.6875rem] font-medium tracking-[0.08em] uppercase">
              {item.field.name}
            </dt>
            <dd class="text-primary mt-1 text-sm leading-relaxed break-words">{item.value}</dd>
          </div>
        {/each}
      </dl>
    </section>
  {/if}

  {#if showFreeformTextInput && inputText.trim().length > 0}
    <section class="flex flex-col gap-2 px-1">
      <h4 class="text-primary text-sm font-semibold">{labels.reviewTextTitle}</h4>
      <pre
        class="border-default bg-secondary/25 overflow-x-auto rounded-lg border px-3 py-3 font-mono text-[0.8125rem] leading-relaxed whitespace-pre-wrap">{inputText.trim()}</pre>
    </section>
  {/if}

  {#if reviewFileGroups.length > 0}
    <section class="border-default bg-primary/40 rounded-xl border px-4 py-4">
      <h4 class="text-primary text-sm font-semibold">{labels.reviewFilesTitle}</h4>
      <div class="mt-3 flex flex-col gap-4">
        {#each reviewFileGroups as group (group.step.step_id)}
          <div class="flex flex-col gap-2">
            <p class="text-muted text-[0.6875rem] font-medium tracking-[0.08em] uppercase">
              {labels.runtimeReviewStep(group.step.step_order, getStepLabel(group.step))}
            </p>
            <ul class="flex flex-col gap-1.5">
              {#each group.files as file (file.id)}
                <li
                  class="border-default bg-secondary/20 flex items-center justify-between gap-3 rounded-md border px-3 py-2 text-sm"
                >
                  <span class="min-w-0 truncate">{file.name ?? file.id}</span>
                  {#if file.size}
                    <span class="text-muted shrink-0 text-xs tabular-nums">
                      {formatBytes(file.size)}
                    </span>
                  {/if}
                </li>
              {/each}
            </ul>
          </div>
        {/each}
      </div>
    </section>
  {/if}
</div>
