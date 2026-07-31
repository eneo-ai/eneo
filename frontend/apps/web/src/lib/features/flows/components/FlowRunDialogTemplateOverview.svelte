<script lang="ts">
  import type { FlowRunContractTemplateReadiness } from "@eneo/eneo-js";
  import { m } from "$lib/paraglide/messages";
  import type { FlowRunBlocker } from "$lib/features/flows/flowRunWizard";
  import type { FlowRunDialogLabels } from "./flowRunDialogLabels";
  import {
    getTemplateReadinessMessage,
    getTemplateStatusClasses,
    getTemplateStatusLabel
  } from "./flowRunTemplateStatus";

  let {
    templateReadinessItems,
    publishedFlowVersion,
    currentTemplateBlockers,
    labels
  }: {
    templateReadinessItems: FlowRunContractTemplateReadiness[];
    publishedFlowVersion: number | null | undefined;
    currentTemplateBlockers: FlowRunBlocker[];
    labels: FlowRunDialogLabels;
  } = $props();
</script>

<div class="flex flex-col gap-4">
  <div class="border-default bg-primary rounded-xl border px-4 py-4">
    <div class="flex items-center justify-between gap-3">
      <div>
        <p class="text-sm font-semibold">{labels.templateStatusTitle}</p>
        <p class="text-secondary mt-1 text-sm leading-relaxed">
          {labels.templateStatusDescription}
        </p>
      </div>
      <span
        class="border-default text-secondary rounded-full border px-2.5 py-1 text-xs font-medium"
      >
        {m.flow_run_template_version_badge({ version: publishedFlowVersion ?? "—" })}
      </span>
    </div>
    <div class="mt-4 flex flex-col gap-3">
      {#each templateReadinessItems as item (item.step_id)}
        <div class="border-default bg-secondary/20 rounded-xl border px-4 py-3.5">
          <div class="flex flex-wrap items-start justify-between gap-3">
            <div class="min-w-0">
              <p class="text-sm font-medium">
                {item.template_name ?? labels.templateFallbackName(item.step_id)}
              </p>
              {#if getTemplateReadinessMessage(item, labels)}
                <p class="text-secondary mt-1 text-xs leading-relaxed">
                  {getTemplateReadinessMessage(item, labels)}
                </p>
              {/if}
            </div>
            <span
              class={`rounded-full border px-2.5 py-1 text-xs font-medium ${getTemplateStatusClasses(item.status)}`}
            >
              {getTemplateStatusLabel(item.status, labels)}
            </span>
          </div>
        </div>
      {/each}
    </div>
  </div>

  {#if currentTemplateBlockers.length > 0}
    <div
      class="border-warning-default/30 bg-warning-dimmer text-warning-stronger rounded-xl border px-4 py-3 text-sm"
    >
      <p class="font-medium">{labels.runBlockersTitle}</p>
      <ul class="mt-2 space-y-1.5">
        {#each currentTemplateBlockers as blocker (blocker.id)}
          <li>{blocker.title}</li>
        {/each}
      </ul>
    </div>
  {/if}
</div>
