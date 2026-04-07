<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import type { CompletionModel, EmbeddingModel, TranscriptionModel } from "@intric/intric-js";
  import { Button, Tooltip } from "@intric/ui";
  import { writable } from "svelte/store";
  import ModelNameAndVendor from "$lib/features/ai-models/components/ModelNameAndVendor.svelte";
  import EditModelDialog from "./EditModelDialog.svelte";
  import { m } from "$lib/paraglide/messages";

  export let model: CompletionModel | EmbeddingModel | TranscriptionModel;
  export let type: "completionModel" | "embeddingModel" | "transcriptionModel";
  $: isTenantModel = model.provider_id != null;

  const showEditDialog = writable(false);
</script>

<div class="flex items-center gap-3">
  {#if isTenantModel}
    <Button on:click={() => showEditDialog.set(true)}>
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
          inline-flex items-center px-2 py-[2px]
          rounded-full text-[11px] font-medium tracking-wide cursor-default
          bg-transparent
          text-[oklch(50%_0.08_78)] dark:text-[oklch(70%_0.08_78)]
          border border-[oklch(75%_0.06_78)] dark:border-[oklch(40%_0.06_78)]
        "
      >
        {m.default_model()}
      </div>
    </Tooltip>
  {/if}
</div>

{#if isTenantModel}
  <EditModelDialog {model} {type} openController={showEditDialog} />
{/if}
