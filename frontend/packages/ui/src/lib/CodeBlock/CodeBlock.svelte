<script lang="ts">
  import hljs from "highlight.js/lib/core";
  import js from "highlight.js/lib/languages/javascript";
  import python from "highlight.js/lib/languages/python";
  import c from "highlight.js/lib/languages/c";
  import xml from "highlight.js/lib/languages/xml";
  import { IconCopy } from "@eneo/icons/copy";

  hljs.registerLanguage("javascript", js);
  hljs.registerLanguage("python", python);
  hljs.registerLanguage("c", c);
  hljs.registerLanguage("xml", xml);

  export let source: string;
  let cls = "";
  export { cls as class };

  let showCopiedMessage = false;
  // Maybe we can do smth here, marked will take the lang from the source
  // export let lang: string | undefined = undefined
  $: highlighted = hljs.highlightAuto(source, ["javascript", "python", "c"]).value;
</script>

<div class="code-wrapper group relative p-0" style="color-scheme: dark;">
  <!-- Pre will print new lines, so this is a bit scuffed -->
  <pre
    class={[
      "bg-overlay-stronger w-full overflow-auto rounded-lg px-8 py-7",
      cls
    ]}><!-- eslint-disable svelte/no-at-html-tags --><code class="hljs">{@html highlighted}</code
    ></pre>

  <button
    class="border-stronger bg-secondary hover:bg-tertiary absolute top-2 right-2 hidden gap-1 rounded-md border p-1 shadow group-hover:flex"
    on:click={() => {
      navigator.clipboard.writeText(source);
      showCopiedMessage = true;
      setTimeout(() => {
        showCopiedMessage = false;
      }, 1000);
    }}
    ><IconCopy></IconCopy>
    {#if showCopiedMessage}
      <span class="text-base">Copied!</span>
    {/if}</button
  >
</div>

<style>
  /* HLJS styles below... */
  :global(.hljs),
  :global(.hljs-subst) {
    color: #d8dee9;
  }
  :global(.hljs-selector-tag) {
    color: #81a1c1;
  }
  :global(.hljs-selector-id) {
    color: #8fbcbb;
    font-weight: bold;
  }
  :global(.hljs-selector-class) {
    color: #8fbcbb;
  }
  :global(.hljs-selector-attr) {
    color: #8fbcbb;
  }
  :global(.hljs-property) {
    color: #88c0d0;
  }
  :global(.hljs-selector-pseudo) {
    color: #88c0d0;
  }
  :global(.hljs-addition) {
    background-color: rgba(163, 190, 140, 0.5);
  }
  :global(.hljs-deletion) {
    background-color: rgba(191, 97, 106, 0.5);
  }
  :global(.hljs-built_in),
  :global(.hljs-type) {
    color: #8fbcbb;
  }
  :global(.hljs-class) {
    color: #8fbcbb;
  }
  :global(.hljs-function) {
    color: #88c0d0;
  }
  :global(.hljs-title.hljs-function),
  :global(.hljs-function > .hljs-title) {
    color: #88c0d0;
  }
  :global(.hljs-keyword),
  :global(.hljs-literal),
  :global(.hljs-symbol) {
    color: #81a1c1;
  }
  :global(.hljs-number) {
    color: #b48ead;
  }
  :global(.hljs-regexp) {
    color: #ebcb8b;
  }
  :global(.hljs-string) {
    color: #a3be8c;
  }
  :global(.hljs-title) {
    color: #8fbcbb;
  }
  :global(.hljs-params) {
    color: #d8dee9;
  }
  :global(.hljs-bullet) {
    color: #81a1c1;
  }
  :global(.hljs-code) {
    color: #8fbcbb;
  }
  :global(.hljs-emphasis) {
    font-style: italic;
  }
  :global(.hljs-formula) {
    color: #8fbcbb;
  }
  :global(.hljs-strong) {
    font-weight: bold;
  }
  :global(.hljs-link:hover) {
    text-decoration: underline;
  }
  :global(.hljs-quote) {
    color: #a2aec5;
  }
  :global(.hljs-comment) {
    color: #a2aec5;
  }
  :global(.hljs-doctag) {
    color: #8fbcbb;
  }
  :global(.hljs-meta),
  :global(.hljs-meta .hljs-keyword) {
    color: #5e81ac;
  }
  :global(.hljs-meta .hljs-string) {
    color: #a3be8c;
  }
  :global(.hljs-attr) {
    color: #8fbcbb;
  }
  :global(.hljs-attribute) {
    color: #d8dee9;
  }
  :global(.hljs-name) {
    color: #81a1c1;
  }
  :global(.hljs-section) {
    color: #88c0d0;
  }
  :global(.hljs-tag) {
    color: #81a1c1;
  }
  :global(.hljs-variable) {
    color: #d8dee9;
  }
  :global(.hljs-template-variable) {
    color: #d8dee9;
  }
  :global(.hljs-template-tag) {
    color: #5e81ac;
  }
</style>
