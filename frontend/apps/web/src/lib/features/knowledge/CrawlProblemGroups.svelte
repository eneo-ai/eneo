<script lang="ts">
  import type { CrawlResourceFailure, CrawlRun } from "@eneo/eneo-js";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import SourceProblemGroup from "./components/SourceProblemGroup.svelte";
  import {
    crawlFailureHref,
    crawlFailureReasonHelp,
    crawlFailureReasonLabel
  } from "./crawlRunState";
  import { m } from "$lib/paraglide/messages";

  /** A crawl's failed addresses grouped by reason, as the source's Problems tab shows them. */
  let {
    failures,
    summary,
    kind,
    loading,
    detailsAvailable
  }: {
    /** The failures loaded so far, in page order. */
    failures: CrawlResourceFailure[];
    /** Recorded total per reason; absent for runs without a summary. */
    summary: CrawlRun["failure_summary"];
    /** The summary counts every resource type, so totals are hidden while one type is selected. */
    kind: CrawlResourceFailure["kind"] | null;
    loading: boolean;
    detailsAvailable: boolean;
  } = $props();

  const reasons = $derived([
    ...new Set([
      ...(kind ? [] : Object.keys(summary ?? {})),
      ...failures.map((failure) => failure.reason)
    ])
  ]);
</script>

{#if reasons.length > 0}
  <div class="border-default overflow-hidden rounded-lg border">
    {#each reasons as reason (reason)}
      {@const matching = failures.filter((failure) => failure.reason === reason)}
      {@const total = kind ? undefined : summary?.[reason]}
      <SourceProblemGroup
        title={crawlFailureReasonLabel(reason)}
        advice={crawlFailureReasonHelp(reason)}
        countLabel={total !== undefined
          ? m.website_source_problem_count({ shown: matching.length, total })
          : m.website_source_problem_shown({ shown: matching.length })}
        icon={TriangleAlert}
        open
      >
        <ul class="divide-border divide-y px-4 pb-3 pl-15 text-sm">
          {#each matching as failure (failure.id)}
            {@const href = crawlFailureHref(failure.url)}
            <li class="flex flex-wrap items-baseline gap-3 py-2">
              <span class="text-secondary text-xs"
                >{failure.kind === "page" ? m.page() : m.crawl_failure_file()}</span
              >
              {#if href}
                <!-- eslint-disable svelte/no-navigation-without-resolve -- validated external HTTP(S) address -->
                <a
                  {href}
                  target="_blank"
                  rel="noreferrer"
                  class="text-accent-stronger break-all underline underline-offset-2"
                  >{failure.url}</a
                >
                <!-- eslint-enable svelte/no-navigation-without-resolve -->
              {:else}<span class="break-all">{failure.url}</span>{/if}
            </li>
          {:else}
            <li class="text-secondary py-2">
              {loading
                ? m.loading()
                : !detailsAvailable
                  ? m.crawl_failures_unavailable()
                  : m.website_source_problem_not_loaded()}
            </li>
          {/each}
        </ul>
      </SourceProblemGroup>
    {/each}
  </div>
{/if}
