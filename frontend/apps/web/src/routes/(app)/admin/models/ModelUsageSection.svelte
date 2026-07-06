<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Read-only "who uses this model" panel for the model detail dialog's usage
  tab. Lazily fetches usage on first activation (the tab is not the default),
  then renders the shared `ModelUsageBreakdown`. Works for completion and
  transcription models — only the endpoint differs; both return the same
  `UsageDetail` shape and a `spaces_count`.
-->

<script lang="ts">
  import { getEneo } from "$lib/core/Eneo";
  import { m } from "$lib/paraglide/messages";
  import { Loader2 } from "lucide-svelte";
  import { Button } from "$lib/components/ui/button/index.js";
  import ModelUsageBreakdown from "./ModelUsageBreakdown.svelte";
  import type { UsageDetail } from "./usage";

  let {
    modelId,
    type = "completionModel",
    active = true
  }: {
    modelId: string;
    type?: "completionModel" | "transcriptionModel";
    // Defer the fetch until the usage tab is actually shown.
    active?: boolean;
  } = $props();

  const eneo = getEneo();

  let isLoading = $state(false);
  let loadError = $state<string | null>(null);
  let total = $state(0);
  let details = $state<UsageDetail[]>([]);
  let spacesCount = $state(0);
  // Guards against re-fetching the same model on every effect re-run.
  let loadedFor = $state<string | null>(null);

  async function load() {
    isLoading = true;
    loadError = null;
    total = 0;
    details = [];
    spacesCount = 0;
    const isTranscription = type === "transcriptionModel";
    try {
      const detailsRes = (await (isTranscription
        ? eneo.models.getTranscriptionUsageDetails({ modelId, limit: 100 })
        : eneo.models.getUsageDetails({ modelId, limit: 100 }))) as {
        items?: UsageDetail[];
        total?: number;
      };
      details = detailsRes?.items ?? [];
      total = detailsRes?.total ?? details.length;
      const stats = (await (isTranscription
        ? eneo.models.getTranscriptionUsageStats({ modelId })
        : eneo.models.getUsageStats({ modelId }))) as {
        spaces_count?: number;
      };
      spacesCount = stats.spaces_count ?? 0;
      loadedFor = modelId;
    } catch (err: unknown) {
      console.error("[ModelUsageSection] Failed to load usage:", err);
      loadError = err instanceof Error ? err.message : m.model_usage_load_failed();
    } finally {
      isLoading = false;
    }
  }

  $effect(() => {
    if (!active) return;
    if (isLoading) return;
    if (loadedFor === modelId) return;
    void load();
  });
</script>

{#if isLoading}
  <div class="text-muted-foreground flex items-center gap-2 py-3 text-sm">
    <Loader2 class="size-4 animate-spin" aria-hidden="true" />
    <span>{m.loading()}</span>
  </div>
{:else if loadError}
  <div
    class="border-negative-default bg-negative-dimmer/50 text-negative-stronger rounded-r-md border-l-2 px-4 py-3 text-sm"
    role="alert"
  >
    <div class="flex items-center justify-between gap-4">
      <span>{loadError}</span>
      <Button variant="outline" size="sm" onclick={load}>{m.retry()}</Button>
    </div>
  </div>
{:else if total > 0 || spacesCount > 0}
  <ModelUsageBreakdown
    {details}
    {spacesCount}
    title={m.model_usage_title()}
    spacesText={m.model_usage_spaces({ count: spacesCount })}
    filterable
  />
{:else}
  <div class="border-border text-muted-foreground rounded-lg border px-4 py-3 text-sm">
    {m.model_usage_empty()}
  </div>
{/if}
