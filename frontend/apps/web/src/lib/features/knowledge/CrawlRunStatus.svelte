<script lang="ts">
  import type { CrawlRun } from "@eneo/eneo-js";
  import { CircleCheck, CircleX, Clock3, LoaderCircle, TriangleAlert } from "lucide-svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import {
    crawlRunState,
    crawlRunStateLabel,
    isCompletedWithMissingResources
  } from "./crawlRunState";

  let { run }: { run: CrawlRun } = $props();
  const state = $derived(crawlRunState(run));
  const completed = $derived(
    state === "succeeded" || state === "unchanged" || isCompletedWithMissingResources(run)
  );
  const active = $derived(["queued", "running", "finalizing", "stopping"].includes(state));
  const warning = $derived((state === "partial" && !completed) || state === "empty");
  const failed = $derived(state === "failed" || state === "interrupted" || state === "unknown");
</script>

<Badge
  variant={failed ? "destructive" : "secondary"}
  class={completed
    ? "bg-positive-dimmer text-positive-stronger"
    : warning
      ? "bg-warning-dimmer text-warning-stronger"
      : active
        ? "bg-accent-dimmer text-accent-stronger"
        : undefined}
>
  {#if failed}<CircleX aria-hidden="true" data-icon="inline-start" />
  {:else if completed}<CircleCheck aria-hidden="true" data-icon="inline-start" />
  {:else if warning}<TriangleAlert aria-hidden="true" data-icon="inline-start" />
  {:else if state === "queued"}<Clock3 aria-hidden="true" data-icon="inline-start" />
  {:else if state === "running" || state === "finalizing" || state === "stopping"}<LoaderCircle
      aria-hidden="true"
      data-icon="inline-start"
    />{/if}
  {crawlRunStateLabel(isCompletedWithMissingResources(run) ? "succeeded" : state)}
</Badge>
