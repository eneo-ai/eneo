<script lang="ts">
  import type { CrawlResourceFailure } from "@eneo/eneo-js";
  import { crawlFailureHref, crawlFailureReasonLabel } from "./crawlRunState";
  import { m } from "$lib/paraglide/messages";

  /** The compact failed-address list of the crawl details dialog. */
  let { failures }: { failures: CrawlResourceFailure[] } = $props();
</script>

<ul aria-label={m.crawl_failed_addresses()} class="divide-border divide-y text-sm">
  {#each failures as failure (failure.id)}
    {@const href = crawlFailureHref(failure.url)}
    <li class="space-y-1.5 py-3">
      <p class="flex flex-wrap items-baseline gap-x-2 gap-y-1">
        <span class="text-secondary text-xs">
          {failure.kind === "page" ? m.page() : m.crawl_failure_file()}
        </span>
        <span class="text-negative-stronger break-words">
          {crawlFailureReasonLabel(failure.reason)}
        </span>
      </p>
      {#if href}
        <!-- eslint-disable svelte/no-navigation-without-resolve -- validated external HTTP(S) address -->
        <a
          {href}
          target="_blank"
          rel="noreferrer"
          class="text-accent-stronger break-all underline underline-offset-2">{failure.url}</a
        >
        <!-- eslint-enable svelte/no-navigation-without-resolve -->
      {:else}
        <span class="break-all">{failure.url}</span>
      {/if}
    </li>
  {/each}
</ul>
