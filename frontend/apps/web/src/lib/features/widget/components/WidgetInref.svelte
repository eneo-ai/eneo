<!--
  Inline citation inside a streamed answer: a small numbered marker that
  opens the sources list below the message and jumps to the matching entry.
-->
<script lang="ts">
  import type { EneoInrefCustomComponentProps } from "@eneo/ui/components/markdown";
  import { m } from "$lib/paraglide/messages";
  import { getWidgetMessageContext } from "../widgetMessageContext";

  let { token }: EneoInrefCustomComponentProps = $props();

  const message = getWidgetMessageContext();
  const index = $derived(message.referenceIndex(token.id));
</script>

{#if index !== null}
  <a
    class="widget-citation"
    href={`#${message.referenceAnchor(index)}`}
    aria-label={m.widget_citation_label({ number: index + 1 })}
    onclick={(event) => {
      event.preventDefault();
      message.revealSource(index);
    }}>{index + 1}</a
  >
{/if}

<style>
  .widget-citation {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    min-width: 1.125rem;
    height: 1.125rem;
    padding: 0 0.3rem;
    margin-left: 0.125rem;
    border-radius: 9999px;
    background: var(--widget-accent);
    color: var(--widget-on-accent);
    font-size: 0.6875rem;
    font-weight: 600;
    line-height: 1;
    text-decoration: none;
    vertical-align: 0.2em;
  }
  .widget-citation:hover,
  .widget-citation:focus-visible {
    outline: 2px solid var(--widget-accent);
    outline-offset: 1px;
  }
</style>
