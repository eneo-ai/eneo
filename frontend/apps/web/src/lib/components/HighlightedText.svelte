<script lang="ts">
  import { splitSharePointMatches } from "$lib/features/integrations/sharepoint/treeState";

  /**
   * `text` with every case-insensitive occurrence of `query` wrapped in a
   * `<mark>`, so a person can see which part of a name or value a search hit.
   * Renders the plain text when there is no query.
   */
  let { text, query = "" }: { text: string; query?: string } = $props();
</script>

{#if query}
  {#each splitSharePointMatches(text, query) as segment, index (index)}
    {#if segment.match}
      <!-- Highlighter yellow from the theme, so it stays readable in both modes. -->
      <mark class="bg-highlight text-highlight-foreground rounded-sm px-0.5">{segment.text}</mark>
    {:else}
      {segment.text}
    {/if}
  {/each}
{:else}
  {text}
{/if}
