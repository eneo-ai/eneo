<script lang="ts">
  import { m } from "$lib/paraglide/messages";

  export let publishedVersion: number | null | undefined;

  let justChanged = false;
  let prevVersion = publishedVersion;
  $: if (publishedVersion !== prevVersion) {
    prevVersion = publishedVersion;
    justChanged = true;
    setTimeout(() => { justChanged = false; }, 1000);
  }
</script>

<span
  class="inline-flex items-center rounded-md px-2 py-0.5 text-xs font-medium ring-1 ring-inset transition-all duration-200 {publishedVersion != null ? 'bg-blue-50 text-blue-700 ring-blue-600/20' : 'bg-amber-50 text-amber-700 ring-amber-600/20'}"
  class:animate-pulse={justChanged}
>
  {#if publishedVersion != null}
    {m.flow_version_published({ version: String(publishedVersion) })}
  {:else}
    {m.flow_version_draft()}
  {/if}
</span>
