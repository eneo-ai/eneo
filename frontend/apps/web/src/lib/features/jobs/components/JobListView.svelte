<script lang="ts">
  import type { Job } from "@intric/intric-js";
  import { IconLoadingSpinner } from "@intric/icons/loading-spinner";
  import { m } from "$lib/paraglide/messages";

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
        <div
          class="border-dimmer flex items-center justify-between gap-x-3 border-b px-2 py-1.5 whitespace-nowrap last-of-type:border-b-0"
        >
          <div class="flex-shrink truncate pr-4">
            {prefix ? prefix + " " : ""}{job.name ?? job.id}
          </div>
          {#if job.status === "in progress" || job.status === "queued"}
            <IconLoadingSpinner class="animate-spin" />
          {:else if job.status === "failed"}
            <div class="text-negative-default w-48 text-right font-medium">{m.failed()}</div>
          {:else if job.status === "complete"}
            <div class="text-positive-default w-48 text-right font-medium">{m.done()}</div>
          {/if}
        </div>
      {/each}
    </div>
  </div>
{/if}
