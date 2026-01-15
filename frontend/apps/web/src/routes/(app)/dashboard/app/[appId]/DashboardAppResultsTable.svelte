<script lang="ts">
  import type { App, AppRunSparse } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";
  import AppResultStatus from "$lib/features/apps/components/AppResultStatus.svelte";

  export let results: AppRunSparse[];
  export let app: App;

  function formatDate(dateString: string | null | undefined): string {
    if (!dateString) return "";
    const date = new Date(dateString);
    return date.toLocaleDateString("sv-SE", {
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    });
  }
</script>

{#if results.length > 0}
  <div class="flex flex-col">
    {#each results as result (result.id)}
      <a
        href="/dashboard/app/{app.id}/results/{result.id}"
        class="border-default hover:bg-hover-dimmer flex items-center justify-between border-b px-3 py-3"
      >
        <span class="text-secondary text-sm">{formatDate(result.created_at)}</span>
        <AppResultStatus run={result} />
      </a>
    {/each}
  </div>
{:else}
  <div class="text-secondary flex items-center justify-center py-8">
    {m.no_previous_results_found()}
  </div>
{/if}
