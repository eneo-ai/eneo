<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@intric/intric-js";
  import { Button, Tooltip } from "@intric/ui";
  import { writable } from "svelte/store";
  import ModelNameAndVendor from "$lib/features/ai-models/components/ModelNameAndVendor.svelte";
  import ModelDetailDialog from "./ModelDetailDialog.svelte";
  import { m } from "$lib/paraglide/messages";
  import { TriangleAlert, Clock } from "lucide-svelte";

  export let model: CompletionModel | EmbeddingModel | TranscriptionModel;
  export let type: "completionModel" | "embeddingModel" | "transcriptionModel";
  export let completionModels: CompletionModel[] = [];
  $: isTenantModel = model.provider_id != null;

  const showDetailDialog = writable(false);

  $: isDeprecated =
    "deprecation_date" in model &&
    model.deprecation_date &&
    model.deprecation_date <= new Date().toISOString().slice(0, 10);

  $: isRetiring =
    "deprecation_date" in model &&
    model.deprecation_date &&
    model.deprecation_date > new Date().toISOString().slice(0, 10);

  $: statusKey = isDeprecated ? "deprecated" : isRetiring ? "retiring" : "ok";

  $: statusLabel = isDeprecated
    ? m.model_label_deprecated()
    : isRetiring
      ? m.model_label_retiring({ date: ("deprecation_date" in model ? model.deprecation_date : "") ?? "" })
      : !model.is_org_enabled
        ? m.model_status_disabled()
        : m.model_status_active();
</script>

<div class="flex items-center gap-3">
  <Tooltip text={statusLabel}>
    {#if isDeprecated}
      <span class="flex-shrink-0 text-negative-default" role="img" aria-label={statusLabel} data-status="deprecated">
        <TriangleAlert size={14} />
      </span>
    {:else if isRetiring}
      <span class="flex-shrink-0 text-warning-default" role="img" aria-label={statusLabel} data-status="retiring">
        <Clock size={14} />
      </span>
    {:else}
      <span
        class="block h-2 w-2 rounded-full flex-shrink-0 {!model.is_org_enabled ? 'bg-negative-default' : 'bg-positive-default'}"
        role="img"
        aria-label={statusLabel}
        data-status={statusKey}
      ></span>
    {/if}
  </Tooltip>

  {#if isTenantModel}
    <Button on:click={() => showDetailDialog.set(true)}>
      <ModelNameAndVendor {model} />
    </Button>
  {:else}
    <span class="px-3 py-2">
      <ModelNameAndVendor {model} />
    </span>
  {/if}

  {#if "is_org_default" in model && model.is_org_default}
    <Tooltip text={m.default_model_tooltip()}>
      <div
        class="
          inline-flex cursor-default items-center rounded-full
          border border-[oklch(75%_0.06_78)] bg-transparent px-2 py-[2px]
          text-[11px]
          font-medium tracking-wide
          text-[oklch(50%_0.08_78)] dark:border-[oklch(40%_0.06_78)] dark:text-[oklch(70%_0.08_78)]
        "
      >
        {m.default_model()}
      </div>
    </Tooltip>
  {/if}
</div>

{#if isTenantModel}
  <ModelDetailDialog {model} {type} {completionModels} openController={showDetailDialog} />
{/if}
