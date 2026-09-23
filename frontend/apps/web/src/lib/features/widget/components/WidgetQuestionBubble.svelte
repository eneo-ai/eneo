<!--
  The visitor's own message, right-aligned in the widget's accent colour.
  Shared by the settled message and the pending one shown before the first
  chunk, so the two can never drift apart in size or shape.
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";

  let { text }: { text: string } = $props();
</script>

<div class="flex justify-end">
  <p class="widget-bubble max-w-[85%] px-3.5 py-2 text-sm whitespace-pre-wrap">
    <span class="sr-only">{m.widget_you()}: </span>{text}
  </p>
</div>

<style>
  .widget-bubble {
    background: var(--widget-accent);
    color: var(--widget-on-accent);
    border-radius: var(--widget-radius);
    border-bottom-right-radius: 4px;
  }
</style>
