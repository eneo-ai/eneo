<script lang="ts">
  import { onMount } from "svelte";
  import { getContentTabs } from "./ctx";
  import { m } from "$lib/paraglide/messages";

  const {
    elements: { list },
    states: { value }
  } = getContentTabs();

  let port: HTMLDivElement | undefined;

  // The strip scrolls at narrow widths, and nothing brings the selected tab back once
  // it is outside the port: it would keep its state while staying invisible. Moving
  // focus is already handled by the browser, but selection and width changes (window
  // resize, or the strip growing when the webfont replaces the fallback) are not.
  function reveal() {
    port?.querySelector('[data-state="active"]')?.scrollIntoView({
      block: "nearest",
      inline: "nearest"
    });
  }

  // Queried inside the microtask: this runs before the DOM is patched, so looking the
  // tab up here would find the one on its way out.
  $: if (port && $value) queueMicrotask(() => reveal());

  onMount(() => {
    if (!port) return;
    const observer = new ResizeObserver(() => reveal());
    observer.observe(port);
    for (const child of Array.from(port.children)) observer.observe(child);
    return () => observer.disconnect();
  });
</script>

<!--
  Labels stay on one line and the strip scrolls once they no longer fit: the header
  row has a fixed height, so a wrapped second line would collide with the title.
  The vertical padding, cancelled by the negative margin, keeps the active segment's
  shadow, the focus outline and the overflow scrollbar inside the scroll port
  without changing the row height.
-->
<div bind:this={port} class="my-[-0.5rem] mr-auto flex min-w-0 items-center overflow-x-auto py-2">
  <div
    {...$list}
    use:list
    class="bg-secondary inline-flex w-fit items-center gap-[2px] rounded-lg p-[3px] whitespace-nowrap"
    aria-label={m.main_views_available_for_current_resource()}
  >
    <slot />
  </div>
</div>
