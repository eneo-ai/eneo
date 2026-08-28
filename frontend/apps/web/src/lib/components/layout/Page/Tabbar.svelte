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
  Labels stay on one line inside a strip that scrolls when the responsive header
  wraps or becomes too narrow. The vertical padding keeps the active segment's
  shadow, focus outline, and scrollbar inside the scroll port.
-->
<div
  bind:this={port}
  class="text-primary left-[50%] my-[-0.5rem] flex min-w-0 flex-grow items-center justify-center overflow-x-auto py-2 pr-3 max-lg:order-2 max-lg:w-full max-lg:flex-none max-lg:justify-start @4xl:lg:absolute @4xl:lg:-translate-x-[50%]"
>
  <div
    {...$list}
    use:list
    class="bg-secondary inline-flex w-fit items-center gap-[2px] rounded-lg p-[3px] whitespace-nowrap"
    aria-label={m.main_views_available_for_current_resource()}
  >
    <slot />
  </div>
</div>
