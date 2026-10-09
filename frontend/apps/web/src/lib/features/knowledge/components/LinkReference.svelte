<script lang="ts">
  import type { InfoBlob } from "@eneo/eneo-js";
  import { IconLinkExternal } from "@eneo/icons/link-external";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Tooltip from "$lib/components/ui/tooltip/index.js";
  import SourceMetadataList from "./SourceMetadataList.svelte";
  import { hasSourceMetadata } from "../sourceMetadata";

  let { blob, index }: { blob: InfoBlob; index?: number } = $props();
</script>

{#snippet chip(props: Record<string, unknown> = {})}
  <Button
    {...props}
    href={blob.metadata.url ?? ""}
    target="_blank"
    variant="ghost"
    class="bg-primary border-default max-w-[30ch] shadow-sm"
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
{/snippet}

{#if hasSourceMetadata(blob)}
  <!-- The source system's properties (SharePoint columns) say what kind of
       document this is; the chip itself only has room for the title. -->
  <Tooltip.Root>
    <Tooltip.Trigger>
      {#snippet child({ props })}
        {@render chip(props)}
      {/snippet}
    </Tooltip.Trigger>
    <Tooltip.Content class="flex-col items-start">
      <SourceMetadataList entries={blob.source_metadata} variant="inline" />
    </Tooltip.Content>
  </Tooltip.Root>
{:else}
  {@render chip()}
{/if}
