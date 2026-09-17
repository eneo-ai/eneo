<!--
  Inline citation inside a streamed answer: a small numbered marker that
  jumps to the matching entry in the sources list below the message.
-->
<script lang="ts">
  import { getWidgetMessageContext } from "../widgetMessageContext";

  // Shape of the `<inref>` token the Markdown renderer hands custom components.
  let { token }: { token: { id: string } } = $props();

  const message = getWidgetMessageContext();
  const index = $derived(message.referenceIndex(token.id));
</script>

{#if index !== null}
  <a
    class="text-accent-default ml-0.5 align-super text-xs font-semibold no-underline hover:underline"
    href={`#${message.referenceAnchor(index)}`}>[{index + 1}]</a
  >
{/if}
