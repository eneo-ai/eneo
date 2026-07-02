<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@eneo/eneo-js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { writable } from "svelte/store";
  import ModelNameAndVendor from "$lib/features/ai-models/components/ModelNameAndVendor.svelte";
  import ModelDetailDialog from "./ModelDetailDialog.svelte";
  import { m } from "$lib/paraglide/messages";
  import { TriangleAlert, Clock } from "lucide-svelte";
  import { getDeprecationStatus } from "$lib/features/ai-models/formatModelStats";

  type AnyModel = CompletionModel | EmbeddingModel | TranscriptionModel;
  type ModelTypeKey = "completionModel" | "embeddingModel" | "transcriptionModel";

  // Rendered via svelte-headless-table's `createRender`, which requires the
  // legacy `export let` API. Keep this file on Svelte 4 component syntax.
  export let model: AnyModel;
  export let type: ModelTypeKey;
  export let completionModels: CompletionModel[] = [];

  $: isTenantModel = model.provider_id != null;

  const showDetailDialog = writable(false);

  $: deprecation = getDeprecationStatus(
    "deprecation_date" in model ? model : { deprecation_date: null }
  );
  $: isDeprecated = deprecation.kind === "deprecated";
  $: isRetiring = deprecation.kind === "retiring";

  $: statusKey = isDeprecated ? "deprecated" : isRetiring ? "retiring" : "ok";

  $: statusLabel = isDeprecated
    ? m.model_label_deprecated()
    : isRetiring && deprecation.date
      ? m.model_label_retiring({ date: deprecation.date })
      : !model.is_org_enabled
        ? m.model_status_disabled()
        : m.model_status_active();
</script>

<div class="flex items-center gap-3">
  <Tooltip.Provider delayDuration={150}>
    <Tooltip.Root>
      <Tooltip.Trigger>
        {#snippet child({ props })}
          <span {...props} class="flex-shrink-0">
            {#if isDeprecated}
              <span class="text-negative-default block" data-status="deprecated">
                <TriangleAlert size={14} aria-hidden="true" />
                <span class="sr-only">{statusLabel}</span>
              </span>
            {:else if isRetiring}
              <span class="text-warning-default block" data-status="retiring">
                <Clock size={14} aria-hidden="true" />
                <span class="sr-only">{statusLabel}</span>
              </span>
            {:else}
              <span
                class="block h-2 w-2 rounded-full {!model.is_org_enabled
                  ? 'bg-negative-default'
                  : 'bg-positive-default'}"
                data-status={statusKey}
                aria-hidden="true"
              ></span>
              <span class="sr-only">{statusLabel}</span>
            {/if}
          </span>
        {/snippet}
      </Tooltip.Trigger>
      <Tooltip.Content>{statusLabel}</Tooltip.Content>
    </Tooltip.Root>
  </Tooltip.Provider>

  {#if isTenantModel}
    <Button variant="ghost" size="sm" onclick={() => showDetailDialog.set(true)}>
      <ModelNameAndVendor {model} descriptionMode="hidden" />
    </Button>
  {:else}
    <span class="px-3 py-2">
      <ModelNameAndVendor {model} />
    </span>
  {/if}

  {#if "is_org_default" in model && model.is_org_default}
    <Tooltip.Provider delayDuration={150}>
      <Tooltip.Root>
        <Tooltip.Trigger>
          {#snippet child({ props })}
            <div
              {...props}
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
          {/snippet}
        </Tooltip.Trigger>
        <Tooltip.Content>{m.default_model_tooltip()}</Tooltip.Content>
      </Tooltip.Root>
    </Tooltip.Provider>
  {/if}
</div>

{#if isTenantModel}
  <ModelDetailDialog {model} {type} {completionModels} openController={showDetailDialog} />
{/if}
