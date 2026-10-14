<script lang="ts">
  import SourceStateBadge from "$lib/features/integrations/components/SourceStateBadge.svelte";
  import SyncProgressBar from "$lib/features/integrations/components/SyncProgressBar.svelte";
  import type { SourceSummary } from "$lib/features/integrations/sources";
  import { m } from "$lib/paraglide/messages";

  interface Props {
    summary: SourceSummary;
    sourceName: string;
    problemsHref: string;
  }

  let { summary, sourceName, problemsHref }: Props = $props();
</script>

{#if summary.progress}
  {@const progress = summary.progress}
  <div class="flex w-40 max-w-full flex-col gap-1.5 text-xs">
    <span class="text-accent-stronger font-medium">
      {progress.total === null
        ? m.integration_progress_syncing_so_far({ count: progress.done })
        : m.integration_progress_syncing_of_total({ done: progress.done, total: progress.total })}
    </span>
    <SyncProgressBar {progress} label={m.integration_progress_label({ name: sourceName })} />
  </div>
{:else}
  <div class="flex flex-col items-start gap-1">
    <SourceStateBadge state={summary.state} />
    {#if summary.state === "attention"}
      <!-- eslint-disable svelte/no-navigation-without-resolve -- link is a typed prop passed from caller -->
      <a
        href={problemsHref}
        class="text-negative-stronger focus-visible:ring-stronger rounded text-xs hover:underline focus-visible:ring-2 focus-visible:outline-none"
      >
        {m.integration_source_show_problems()}
      </a>
      <!-- eslint-enable svelte/no-navigation-without-resolve -->
    {/if}
  </div>
{/if}
