<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { formatSourceMetadataValue, type SourceMetadataEntry } from "../sourceMetadata";

  /**
   * The document properties a source system keeps about a document (SharePoint
   * library columns), as a description list in the source's own column order.
   *
   * `list` is the readable form for a dialog or panel; `inline` packs
   * "Label: value" pairs on one wrapping line for tooltips and chips, where it
   * inherits the surrounding text colour.
   */
  let {
    entries,
    variant = "list",
    class: className = ""
  }: {
    entries: SourceMetadataEntry[];
    variant?: "list" | "inline";
    class?: string;
  } = $props();

  const labels = $derived({ yes: m.yes(), no: m.no() });
</script>

{#if entries.length > 0}
  {#if variant === "inline"}
    <dl
      aria-label={m.source_metadata_label()}
      class={["flex flex-wrap gap-x-3 gap-y-0.5", className]}
    >
      {#each entries as entry (entry.name)}
        <div class="inline-flex gap-1">
          <dt class="opacity-80">{entry.label}:</dt>
          <dd class="font-medium">{formatSourceMetadataValue(entry, labels)}</dd>
        </div>
      {/each}
    </dl>
  {:else}
    <dl
      aria-label={m.source_metadata_label()}
      class={["grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm", className]}
    >
      {#each entries as entry (entry.name)}
        <dt class="text-muted-foreground">{entry.label}</dt>
        <dd class="break-words">{formatSourceMetadataValue(entry, labels)}</dd>
      {/each}
    </dl>
  {/if}
{/if}
