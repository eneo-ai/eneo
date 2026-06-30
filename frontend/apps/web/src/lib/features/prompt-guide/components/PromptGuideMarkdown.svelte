<!--
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<!--
  Small markdown renderer scoped to the Prompt Guide modal. The modal is built
  on shadcn primitives, and the repo's only Markdown component lives in
  `@eneo/ui` — importing it here would break the "don't mix the two UI
  systems in one file" rule (see `$lib/components/ui/README.md`). So we render
  markdown locally with `marked` + DOMPurify instead of cross-importing.
-->

<script lang="ts">
  import { browser } from "$app/environment";
  import { marked } from "marked";
  import DOMPurify from "dompurify";
  import type { ClassValue } from "svelte/elements";

  type Props = {
    /** Markdown source — a Prompt Guide reply. */
    source: string;
    class?: ClassValue;
  };

  let { source, class: cls }: Props = $props();

  // marked.parse is synchronous here (no `async: true`); DOMPurify strips any
  // script/event-handler the model might emit before it reaches {@html}.
  // Guarded to the browser: the dialog never renders during SSR and DOMPurify
  // needs a DOM, so the server path falls back to escaped text.
  const html = $derived.by(() => {
    if (!browser) return "";
    const rendered = marked.parse(source ?? "", { gfm: true, breaks: true }) as string;
    return DOMPurify.sanitize(rendered);
  });
</script>

<div class={["pg-markdown prose text-sm break-words", cls]}>
  {#if browser}
    <!-- eslint-disable-next-line svelte/no-at-html-tags -- markdown is sanitized with DOMPurify above -->
    {@html html}
  {:else}
    <p class="whitespace-pre-wrap">{source}</p>
  {/if}
</div>

<style>
  /* {@html} output isn't scoped, so the rendered nodes are targeted with
     :global. `.prose` (from @eneo/ui) styles text/lists/headings but leaves
     code blocks bare — give fenced blocks a card-like surface so the guide's
     final prompt reads as a distinct artifact. */
  .pg-markdown :global(pre) {
    margin: 0.625rem 0;
    padding: 0.75rem 0.875rem;
    border: 1px solid var(--border-color-default);
    border-radius: 0.5rem;
    background-color: var(--background-color-secondary);
    overflow-x: auto;
  }

  .pg-markdown :global(pre code) {
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
    font-size: 0.8125rem;
    line-height: 1.55;
    white-space: pre-wrap;
    word-break: break-word;
  }

  .pg-markdown :global(:not(pre) > code) {
    padding: 0.05rem 0.3rem;
    border-radius: 0.3rem;
    background-color: var(--background-color-secondary);
    font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "Liberation Mono", monospace;
  }

  /* Trim the outer margins so the rendered block sits flush in a chat bubble. */
  .pg-markdown :global(> :first-child) {
    margin-top: 0;
  }
  .pg-markdown :global(> :last-child) {
    margin-bottom: 0;
  }
</style>
