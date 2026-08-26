<script lang="ts">
  import ChunkSettings from "./ChunkSettings.svelte";

  // Test-only fixture: binds ChunkSettings' props and prints them, so a test can
  // assert on what would actually be submitted.
  export let chunkSize: number | null = null;
  export let chunkOverlap: number | null = null;
  export let maxInput: number | null | undefined = undefined;
</script>

<ChunkSettings bind:chunkSize bind:chunkOverlap {maxInput} />

<!-- eslint-disable eneo/no-hardcoded-text -- test-only fixture -->
<output data-testid="submitted">
  size={chunkSize === null ? "null" : chunkSize}, overlap={chunkOverlap === null
    ? "null"
    : chunkOverlap}
</output>
