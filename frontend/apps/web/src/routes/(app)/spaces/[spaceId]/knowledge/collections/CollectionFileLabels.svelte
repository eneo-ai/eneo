<script lang="ts">
  import { type GroupSparse } from "@intric/intric-js";
  import { m } from "$lib/paraglide/messages";
  
  export let collection: Pick<GroupSparse, "metadata">;
</script>

<div class="flex items-center">
  {#if collection.metadata}
    {#if collection.metadata.num_info_blobs > 0}
      <span
        class="label-blue border-label-default bg-label-dimmer text-label-stronger block min-w-16 rounded-md border px-2 py-1 text-center text-sm"
        >{m.files({ count: collection.metadata.num_info_blobs })}</span
      >
    {:else}
      <span
        class="label-grey border-label-default bg-label-dimmer text-label-stronger block min-w-16 rounded-md border px-2 py-1 text-center text-sm"
        >{m.empty()}</span
      >
    {/if}
  {/if}
</div>
