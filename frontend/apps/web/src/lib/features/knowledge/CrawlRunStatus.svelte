<script lang="ts">
  import type { CrawlRun } from "@eneo/eneo-js";
  import { CircleCheck, CircleX, Clock3, LoaderCircle, TriangleAlert } from "lucide-svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { crawlRunState, crawlRunStateLabel } from "./crawlRunState";

  let { run }: { run: CrawlRun } = $props();
  const state = $derived(crawlRunState(run));
  const failed = $derived(state === "failed" || state === "interrupted" || state === "unknown");
</script>

<Badge variant={failed ? "destructive" : "secondary"}>
  {#if failed}<CircleX aria-hidden="true" data-icon="inline-start" />
  {:else if state === "partial"}<TriangleAlert aria-hidden="true" data-icon="inline-start" />
  {:else if state === "succeeded" || state === "unchanged"}<CircleCheck
      aria-hidden="true"
      data-icon="inline-start"
    />
  {:else if state === "queued"}<Clock3 aria-hidden="true" data-icon="inline-start" />
  {:else if state === "running" || state === "finalizing" || state === "stopping"}<LoaderCircle
      aria-hidden="true"
      data-icon="inline-start"
    />{/if}
  {crawlRunStateLabel(state)}
</Badge>
