<script lang="ts">
  import type { Tokens } from "marked";
  import { hasChildTokens, isSupportedToken, renderers, type SupportedToken } from ".";
  import Generic from "./Generic.svelte";
  import Self from "./RenderToken.svelte";
  import type { Component, Snippet } from "svelte";

  type Props = { token: SupportedToken | SupportedToken[] | Tokens.Generic | Tokens.Generic[] };

  const { token }: Props = $props();
  const tokens = $derived(Array.isArray(token) ? token : [token]);

  function getRenderer(
    token: SupportedToken | Tokens.Generic
  ): [
    Component<{ token: typeof token; children?: Snippet }>,
    { token: typeof token; children?: SupportedToken[] }
  ] {
    if (isSupportedToken(token)) {
      const renderer = renderers[token.type] as Component;
      return [renderer, { token, children: hasChildTokens(token) ? token.tokens : undefined }];
    }
    return [Generic, { token }];
  }
</script>

{#each tokens as token, i (i)}
  {@const [Component, props] = getRenderer(token)}
  {#if props.children}
    <Component token={props.token}>
      <Self token={props.children}></Self>
    </Component>
  {:else}
    <Component token={props.token}></Component>
  {/if}
{/each}
