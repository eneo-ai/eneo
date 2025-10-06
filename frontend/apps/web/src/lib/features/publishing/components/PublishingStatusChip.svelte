<script lang="ts">
  import { IconCheck } from "@intric/icons/check";
  import type { PublishableResource } from "../Publisher";

  export let resource: PublishableResource;
  
  import { m } from "$lib/paraglide/messages";
</script>

{#if resource.published}
  <div
    class="border-positive-default bg-positive-dimmer text-positive-stronger flex w-full items-center justify-center gap-2 rounded-lg border px-2 py-1"
  >
    <IconCheck></IconCheck>
    {m.published()}
  </div>
{:else}
  <div
    class="text-secondary flex w-full items-center justify-center gap-2 rounded-lg border px-2 py-1"
  >
    {m.draft()}
  </div>
{/if}
