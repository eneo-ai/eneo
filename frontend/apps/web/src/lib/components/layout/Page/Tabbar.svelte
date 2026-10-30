<script lang="ts">
  import { onMount } from "svelte";
  import { Tabs } from "bits-ui";
  import { getContentTabs } from "./ctx";
  import { m } from "$lib/paraglide/messages";

  const { value } = getContentTabs();

  let port: HTMLDivElement | undefined;

  // The strip scrolls at narrow widths, and nothing brings a tab back once it is
  // outside the port: it would keep its state while staying invisible. Activation is
  // manual, so arrow keys move focus without selecting, and Chromium does not scroll a
  // partly clipped tab into view when it takes focus. A focus move, a selection change
  // and a width change (window resize, or the strip growing when the webfont replaces
  // the fallback) therefore all reveal the tab: the focused one first, so a width
  // change does not scroll the user's place out of view.
  function reveal() {
    const target =
      port?.querySelector('[role="tab"]:focus') ?? port?.querySelector('[data-state="active"]');
    target?.scrollIntoView({ block: "nearest", inline: "nearest" });
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
  on:focusin={reveal}
  class="my-[-0.5rem] mr-auto flex min-w-0 items-center overflow-x-auto overflow-y-hidden py-2"
>
  <Tabs.List
    class="bg-secondary inline-flex w-fit items-center gap-[2px] rounded-lg p-[3px] whitespace-nowrap"
    aria-label={m.main_views_available_for_current_resource()}
  >
    <slot />
  </Tabs.List>
</div>
