<script lang="ts">
  import { untrack } from "svelte";
  // Test double for a citation renderer that caches on mount, like BlobPreview.
  const { token }: { token: { id: string } } = $props();
  // Capturing the mount-time id is the point of the probe.
  const mountedWith = untrack(() => token.id);
</script>

<span data-inref-probe data-current={token.id} data-mounted={mountedWith}>[{token.id}]</span>
