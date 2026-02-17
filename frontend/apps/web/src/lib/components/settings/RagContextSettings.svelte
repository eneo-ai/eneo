<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<script lang="ts">
  import { Input, Select } from "@intric/ui";
  import { m } from "$lib/paraglide/messages";

  type RagContextType = "percentage" | "fixed_chunks" | "auto_relevance" | null;
  // Select.Simple treats null as falsy and won't pre-select it, so use a sentinel
  type InternalType = "default" | "percentage" | "fixed_chunks" | "auto_relevance";

  interface Props {
    ragContextType: RagContextType;
    ragContextValue: number | null;
    hasChanges?: boolean;
    modelTokenLimit?: number | null;
    labelId?: string;
    descriptionId?: string;
  }

  let {
    ragContextType = $bindable(),
    ragContextValue = $bindable(),
    hasChanges = false,
    modelTokenLimit = null,
    labelId,
    descriptionId
  }: Props = $props();

  // Internal value that maps null <-> "default" for the select component
  let internalType: InternalType = $state(ragContextType ?? "default");

  // Sync outward: internal -> external
  $effect(() => {
    ragContextType = internalType === "default" ? null : internalType;
  });

  // Sync inward: external -> internal (e.g. on revert)
  $effect(() => {
    const expected = ragContextType ?? "default";
    if (internalType !== expected) {
      internalType = expected;
    }
  });

  // Options for the RAG context type
  const contextTypeOptions: Array<{ value: InternalType; label: string }> = [
    { value: "default", label: m.rag_context_default?.() ?? "50% of context (Default)" },
    { value: "auto_relevance", label: m.rag_context_auto_relevance?.() ?? "Automatic (by relevance)" },
    { value: "percentage", label: m.rag_context_percentage?.() ?? "Custom percentage" },
    { value: "fixed_chunks", label: m.rag_context_fixed_chunks?.() ?? "Fixed number of chunks" }
  ];

  // Calculate approximate chunks for display
  let approximateChunks = $derived.by(() => {
    if (!modelTokenLimit) return null;
    const tokensPerChunk = 200;
    
    if (internalType === "default") {
      return Math.floor(modelTokenLimit / tokensPerChunk / 2);
    }
    if (internalType === "percentage" && ragContextValue) {
      return Math.floor(modelTokenLimit / tokensPerChunk * ragContextValue / 100);
    }
    if (internalType === "fixed_chunks" && ragContextValue) {
      return ragContextValue;
    }
    return Math.floor(modelTokenLimit / tokensPerChunk / 2);
  });

  // Handle type changes and set sensible defaults
  $effect(() => {
    if (internalType === "percentage" && ragContextValue === null) {
      ragContextValue = 50;
    } else if (internalType === "fixed_chunks" && ragContextValue === null) {
      ragContextValue = 30;
    }
  });
</script>

<div class="rounded-lg border border-default p-4 flex flex-col gap-3">
  <!-- Type selector — {#key} forces re-mount when internalType changes externally (e.g. revert) -->
  <div class="flex flex-col gap-2">
    {#key internalType}
      <Select.Simple
        options={contextTypeOptions}
        bind:value={internalType}
      >
        {m.rag_context_type_label?.() ?? "Context retrieval mode"}
      </Select.Simple>
    {/key}
  </div>

  <!-- Value input based on type -->
  {#if internalType === "percentage"}
    <div class="flex flex-col gap-2 pt-2 border-t border-default">
      <label class="font-medium pl-3">{m.rag_context_percentage_label?.() ?? "Percentage of context"}</label>
      <div class="flex items-center gap-2">
        <Input.Number
          bind:value={ragContextValue}
          min={1}
          max={100}
          hiddenLabel
          class="w-[100px]"
        >
          {m.rag_context_percentage_label?.() ?? "Percentage of context"}
        </Input.Number>
        <span class="text-default-dimmer text-sm">%</span>
        {#if approximateChunks !== null}
          <span class="text-muted text-xs ml-1">
            (~{approximateChunks} {m.rag_context_chunks?.() ?? "chunks"})
          </span>
        {/if}
      </div>
    </div>
  {:else if internalType === "fixed_chunks"}
    <div class="flex flex-col gap-2 pt-2 border-t border-default">
      <label class="font-medium pl-3">{m.rag_context_chunks_label?.() ?? "Number of chunks"}</label>
      <div class="flex items-center gap-2">
        <Input.Number
          bind:value={ragContextValue}
          min={1}
          max={1000}
          hiddenLabel
          class="w-[100px]"
        >
          {m.rag_context_chunks_label?.() ?? "Number of chunks"}
        </Input.Number>
        <span class="text-default-dimmer text-sm">{m.rag_context_chunks?.() ?? "chunks"}</span>
      </div>
    </div>
  {:else}
    {#if internalType === "auto_relevance"}
      <div class="text-muted text-xs pt-2 border-t border-default">
        {m.rag_context_auto_relevance_help?.() ?? "Automatically determines how many chunks to include based on relevance. Only chunks with high similarity to the question are used."}
      </div>
    {:else if approximateChunks !== null}
      <div class="text-muted text-xs pt-2 border-t border-default">
        {m.rag_context_approximate?.() ?? "Approximately"} {approximateChunks} {m.rag_context_chunks?.() ?? "chunks"}
      </div>
    {/if}
  {/if}

  <!-- Help text -->
  <div class="text-muted text-xs">
    {m.rag_context_help?.() ?? "Controls how much knowledge is retrieved when the assistant answers questions. More chunks means more context but slower responses."}
  </div>
</div>