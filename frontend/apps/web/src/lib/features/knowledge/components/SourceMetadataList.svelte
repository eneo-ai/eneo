<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import HighlightedText from "$lib/components/HighlightedText.svelte";
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
    highlight = "",
    class: className = ""
  }: {
    entries: SourceMetadataEntry[];
    variant?: "list" | "inline";
    /** Normalised search query whose occurrences are marked in labels and values. */
    highlight?: string;
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
          <dt class="opacity-80"><HighlightedText text={entry.label} query={highlight} />:</dt>
          <dd class="font-medium">
            <HighlightedText text={formatSourceMetadataValue(entry, labels)} query={highlight} />
          </dd>
        </div>
      {/each}
    </dl>
  {:else}
    <dl
      aria-label={m.source_metadata_label()}
      class={["grid grid-cols-[max-content_1fr] gap-x-4 gap-y-1 text-sm", className]}
    >
      {#each entries as entry (entry.name)}
        <dt class="text-muted-foreground">
          <HighlightedText text={entry.label} query={highlight} />
        </dt>
        <dd class="break-words">
          <HighlightedText text={formatSourceMetadataValue(entry, labels)} query={highlight} />
        </dd>
      {/each}
    </dl>
  {/if}
{/if}
