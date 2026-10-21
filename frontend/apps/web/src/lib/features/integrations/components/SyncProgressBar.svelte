<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import {
    progressFraction,
    type SyncProgressSummary
  } from "$lib/features/integrations/syncProgress";

  interface Props {
    progress: SyncProgressSummary;
    /** Accessible name of the bar. */
    label: string;
    size?: "sm" | "md";
    class?: string;
  }

  let { progress, label, size = "sm", class: className = "" }: Props = $props();

  let fraction = $derived(progressFraction(progress));
  let readable = $derived(progress.indexed + progress.unchanged);
  let readableWidth = $derived(
    progress.total ? Math.min(100, (readable / progress.total) * 100) : 0
  );
  let skippedWidth = $derived(
    progress.total ? Math.min(100 - readableWidth, (progress.skipped / progress.total) * 100) : 0
  );
  let doneText = $derived(
    progress.total !== null
      ? m.integration_progress_done_of_total({ done: progress.done, total: progress.total })
      : progress.done === 1
        ? m.integration_progress_done_so_far_one()
        : m.integration_progress_done_so_far_other({ count: progress.done })
  );
  // The skipped share is a colour of its own; the value text says it too.
  let valueText = $derived(
    progress.skipped > 0
      ? `${doneText}, ${m.integration_progress_skipped({ count: progress.skipped })}`
      : doneText
  );
</script>

<div
  role="progressbar"
  aria-label={label}
  aria-valuemin={0}
  aria-valuemax={progress.total ?? undefined}
  aria-valuenow={fraction === null ? undefined : progress.done}
  aria-valuetext={valueText}
  class="bg-tertiary relative flex w-full overflow-hidden rounded-full {size === 'md'
    ? 'h-2'
    : 'h-1'} {className}"
>
  {#if fraction === null}
    <span class="indeterminate bg-accent-default absolute inset-y-0 w-1/3 rounded-full"></span>
  {:else}
    <span
      class="bg-accent-default h-full motion-safe:transition-[width]"
      style:width="{readableWidth}%"
    ></span>
    <span
      class="bg-warning-default h-full motion-safe:transition-[width]"
      style:width="{skippedWidth}%"
    ></span>
  {/if}
</div>

<style>
  .indeterminate {
    animation: slide 1.6s ease-in-out infinite;
  }

  @keyframes slide {
    from {
      left: -33%;
    }
    to {
      left: 100%;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .indeterminate {
      animation: none;
      left: 0;
      width: 100%;
      opacity: 0.4;
    }
  }
</style>
