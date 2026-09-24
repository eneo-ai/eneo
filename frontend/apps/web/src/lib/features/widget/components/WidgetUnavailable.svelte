<!--
  The panel's content for a paused, archived or unknown widget. It joins the
  loader's protocol like the chat does: focus moves to the notice when the
  panel opens, so a screen reader reads it, and the visitor closes it from
  here with the button or Escape.
-->
<script lang="ts">
  import { onMount, untrack } from "svelte";
  import { X } from "@lucide/svelte";
  import { m } from "$lib/paraglide/messages";
  import { createEmbedBridge } from "../embedBridge";

  let { hostOrigin }: { hostOrigin: string | null } = $props();

  let heading = $state<HTMLHeadingElement | null>(null);

  const bridge = createEmbedBridge({
    hostOrigin: untrack(() => hostOrigin),
    handlers: { onOpen: () => heading?.focus() }
  });

  onMount(() => {
    bridge.ready();
    return () => bridge.destroy();
  });

  function onWindowKeydown(event: KeyboardEvent) {
    if (event.key !== "Escape" || event.defaultPrevented || !bridge.embedded) return;
    event.preventDefault();
    bridge.close();
  }
</script>

<svelte:window onkeydown={onWindowKeydown} />

<div
  class="bg-primary text-primary fixed inset-0 flex flex-col items-center justify-center gap-2 p-6"
>
  {#if bridge.embedded}
    <button
      type="button"
      class="widget-notice-close hover:bg-secondary absolute top-3 right-3"
      onclick={() => bridge.close()}
      aria-label={m.widget_close()}
      title={m.widget_close()}
    >
      <X class="size-5" aria-hidden="true" />
    </button>
  {/if}
  <h1 class="text-base font-semibold" tabindex="-1" bind:this={heading}>
    {m.widget_not_available_title()}
  </h1>
  <p class="text-secondary text-center text-sm">{m.widget_not_available_body()}</p>
</div>

<style>
  .widget-notice-close {
    display: flex;
    width: 2.25rem;
    height: 2.25rem;
    align-items: center;
    justify-content: center;
    border-radius: 9999px;
  }
  .widget-notice-close:focus-visible {
    outline: 2px solid currentColor;
    outline-offset: 2px;
  }
</style>
