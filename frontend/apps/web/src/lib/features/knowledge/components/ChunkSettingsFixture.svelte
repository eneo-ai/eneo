<script lang="ts">
  import ChunkSettings from "./ChunkSettings.svelte";

  // Test-only fixture: ChunkSettings communicates through bound props, and a rendered
  // component does not expose them as accessors. Binding here and printing the values
  // lets a test assert on what would actually be submitted, rather than on internals.
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
