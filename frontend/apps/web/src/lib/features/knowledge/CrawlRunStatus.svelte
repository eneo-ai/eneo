<script lang="ts">
  import type { CrawlRun } from "@eneo/eneo-js";
  import { CircleCheck, CircleX, Clock3, LoaderCircle, TriangleAlert } from "lucide-svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { m } from "$lib/paraglide/messages";
  import {
    crawlRunState,
    crawlRunStateLabel,
    isCompletedWithMissingResources,
    isMinorPartial
  } from "./crawlRunState";

  let { run }: { run: CrawlRun } = $props();
  const state = $derived(crawlRunState(run));
  const missingOnly = $derived(isCompletedWithMissingResources(run));
  const notes = $derived(state === "partial" && !missingOnly && isMinorPartial(run));
  const completed = $derived(
    state === "succeeded" || state === "unchanged" || missingOnly || notes
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
  {missingOnly
    ? crawlRunStateLabel("succeeded")
    : notes
      ? m.crawl_completed_with_notes()
      : crawlRunStateLabel(state)}
</Badge>
