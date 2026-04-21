<script lang="ts">
  import type { IntricInrefToken } from "../CustomComponents";
  import { getReferenceContext } from "../ReferenceContext.js";

  type Props = { token: IntricInrefToken };
  const { token }: Props = $props();

  const {
    state: { references },
    CustomRenderer
  } = getReferenceContext();

  // this shouldn't really need to be reactive, but there is an edge case where references
  // might get shuffled in the references array and like this we keep the correct relationship
  const reference = $derived.by(() => {
    // Only do this when not handled by custom element
    if (CustomRenderer) return;
    const idx = references.current.findIndex((ref) => ref.id.startsWith(token.id));
    if (idx > -1)
      return {
        ...references.current[idx],
        number: idx + 1
      };
  });
</script>

{#if CustomRenderer}
  <CustomRenderer {token} />
{:else if reference}
  <!-- eslint-disable svelte/no-navigation-without-resolve -- external URL from reference metadata -->
  <a
    class="border-stronger bg-secondary hover:bg-hover-stronger inline-block min-h-7 min-w-7 rounded-lg border border-b-2 px-2 text-center font-mono text-base font-normal no-underline hover:cursor-pointer"
    href={reference.metadata.url}
    target="_blank"
    rel="noreferrer">{reference.number}</a
  >
  <!-- eslint-enable svelte/no-navigation-without-resolve -->
{/if}
