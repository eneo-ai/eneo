<script module lang="ts">
  import type KaTeX from "katex";

  // KaTeX and its stylesheet load on the first formula, not with the app. Once
  // loaded, later formulas render on mount without waiting.
  let katex: typeof KaTeX | undefined;
  let loading: Promise<typeof KaTeX> | undefined;

  function loadKatex() {
    loading ??= Promise.all([import("katex"), import("katex/dist/katex.min.css")]).then(
      ([module]) => (katex = module.default),
      (error) => {
        loading = undefined; // a later formula tries again
        throw error;
      }
    );
    return loading;
  }
</script>

<script lang="ts">
  import { katexOptions } from "@eneo/markdown-math";
  import type { EneoMathToken } from "../CustomComponents";

  const { token }: { token: EneoMathToken } = $props();

  let renderer = $state(katex);
  $effect(() => {
    if (renderer) return;
    loadKatex().then(
      (loaded) => (renderer = loaded),
      () => {} // the formula stays as written
    );
  });

  // Streaming hands a new token on every flush; keyed on the source itself, a
  // finished formula is not typeset again while the answer keeps growing.
  const tex = $derived(token.text);
  const display = $derived(token.display);
  const html = $derived.by(() => {
    try {
      return renderer?.renderToString(tex, katexOptions(display));
    } catch {
      // Invalid TeX already renders as an error; this is what KaTeX still
      // throws, such as running out of stack on deep nesting.
      return undefined;
    }
  });
</script>

<!-- Until KaTeX has loaded, or if it cannot, the formula shows as written. -->
{#if token.level === "block"}
  <div class="my-4 overflow-x-auto overflow-y-hidden" data-math="block">
    <!-- eslint-disable-next-line svelte/no-at-html-tags -- KaTeX output with trust: false -->
    {#if html}{@html html}{:else}{token.raw}{/if}
  </div>
{:else}
  <span data-math="inline">
    <!-- eslint-disable-next-line svelte/no-at-html-tags -- KaTeX output with trust: false -->
    {#if html}{@html html}{:else}{token.raw}{/if}
  </span>
{/if}
