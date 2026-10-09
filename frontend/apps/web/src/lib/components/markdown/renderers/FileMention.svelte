<script lang="ts">
  import type { EneoFileToken } from "../CustomComponents";
  import { getReferenceContext } from "../ReferenceContext.js";

  type Props = { token: EneoFileToken };
  const { token }: Props = $props();

  const context = getReferenceContext();
  const FileRenderer = $derived(context.FileRenderer);
</script>

{#if FileRenderer}
  <FileRenderer {token} />
{:else}
  {token.name}
{/if}
