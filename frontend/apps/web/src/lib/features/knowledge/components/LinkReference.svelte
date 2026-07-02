<script lang="ts">
  import type { InfoBlob } from "@eneo/eneo-js";
  import { IconLinkExternal } from "@eneo/icons/link-external";
  import { Button } from "@eneo/ui";
  export let blob: InfoBlob;
  export let index: number | undefined = undefined;
</script>

<Button
  href={blob.metadata.url ?? ""}
  target="_blank"
  variant="simple"
  class="!border-default bg-primary max-w-[30ch] border shadow-sm"
  padding="icon-leading"
>
  {#if index}
    <span
      class="border-default bg-secondary min-h-7 min-w-7 rounded-md border border-b-2 text-center font-mono font-normal"
    >
      {index}
    </span>
  {/if}
  <span class="truncate">
    {blob.metadata.title ?? blob.metadata.url}
  </span>
  <IconLinkExternal class="text-secondary h-6 w-6" />
</Button>
