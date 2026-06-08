<script lang="ts">
  import type { Job } from "@intric/intric-js";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { m } from "$lib/paraglide/messages";
  import ExpandableErrorRow from "./ExpandableErrorRow.svelte";

  export let jobs: Job[];
  export let title: string;
  export let prefix: string | undefined = undefined;
</script>

{#if jobs.length > 0}
  <div class="flex flex-col gap-1 px-2 py-2">
    <span class="pl-3 font-medium">{title}</span>
    <div
      class="border-default bg-primary ring-default min-h-10 items-center justify-between rounded-lg border px-3 py-2 shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
    >
      {#each jobs as job (job.id)}
        {#if job.status === "failed" && job.result_location}
          <ExpandableErrorRow
            label={`${prefix ? prefix + " " : ""}${job.name ?? job.id}`}
            tooltip={job.name ?? job.id}
            message={job.result_location}
            borderClass="border-dimmer"
          />
        {:else}
          <div
            class="border-dimmer flex items-center justify-between gap-x-3 border-b px-2 py-1.5 whitespace-nowrap last-of-type:border-b-0"
          >
            <div class="flex-shrink truncate pr-4" title={job.name ?? job.id}>
              {prefix ? prefix + " " : ""}{job.name ?? job.id}
            </div>
            {#if job.status === "in progress" || job.status === "queued"}
              <IconLoadingSpinner class="animate-spin" />
            {:else if job.status === "failed"}
              <div class="text-negative-default min-w-fit font-medium">{m.failed()}</div>
            {:else if job.status === "complete"}
              <div class="flex w-48 flex-col items-end gap-0.5 text-right">
                <div class="text-positive-default font-medium">{m.done()}</div>
              </div>
            {/if}
          </div>
        {/if}
      {/each}
    </div>
  </div>
{/if}
