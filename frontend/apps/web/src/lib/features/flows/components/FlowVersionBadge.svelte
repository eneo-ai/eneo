<script lang="ts">
  import { m } from "$lib/paraglide/messages";

  export let publishedVersion: number | null | undefined;

  let justChanged = false;
  let prevVersion = publishedVersion;
  $: if (publishedVersion !== prevVersion) {
    prevVersion = publishedVersion;
    justChanged = true;
    setTimeout(() => { justChanged = false; }, 500);
  }
</script>

<span
  class="inline-flex items-center rounded-md px-2.5 py-1 text-sm font-medium ring-1 ring-inset transition-all duration-200 {publishedVersion != null ? 'bg-accent-dimmer text-accent-stronger ring-accent-default/20' : 'bg-warning-dimmer text-warning-stronger ring-warning-default/20'} {justChanged ? 'ring-2 ring-accent-default/50' : ''}"
>
  {#if publishedVersion != null}
    {m.flow_version_published({ version: String(publishedVersion) })}
  {:else}
    {m.flow_version_draft()}
  {/if}
</span>
