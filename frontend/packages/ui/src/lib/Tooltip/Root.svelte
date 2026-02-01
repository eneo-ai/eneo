<script lang="ts">
  import { createTooltip } from "@melt-ui/svelte";

  export let asFragment = false;
  let cls = "";
  export { cls as class };
  export let text: string | undefined;
  export let placement: "left" | "bottom" | "top" | "right" = "top";
  /** Portal to display the tooltip, useful in case of overflows. A CSS selector */
  export let portal: string | null = "body";
  /** Will render the element as "inline", use this when showing tooltips inside text blocks. (e.g when rendering references) */
  export let renderInline = false;

  // Tootltip
  const {
    elements: { trigger, content }
  } = createTooltip({
    positioning: {
      placement,
      sameWidth: false
    },
    openDelay: 350,
    closeDelay: 0,
    closeOnPointerDown: true,
    forceVisible: false,
    portal,
    disableHoverableContent: true
  });
</script>

{#if !text}
  <slot />
{:else if asFragment}
  <slot trigger={[$trigger]} />

  <div
    {...$content}
    use:content
    class="bg-overlay-stronger text-on-fill z-[100] max-w-sm rounded-lg shadow-lg"
  >
    <p class="px-3 py-2 text-sm leading-relaxed">{text}</p>
  </div>
{:else}
  <div {...$trigger} use:trigger class={cls} class:renderInline>
    <slot trigger={[$trigger]} />

    <div
      {...$content}
      use:content
      class="bg-overlay-stronger text-on-fill z-[100] max-w-sm rounded-lg shadow-lg"
    >
      <p class="px-3 py-2 text-sm leading-relaxed">{text}</p>
    </div>
  </div>
{/if}

<style>
  div {
    margin: 0px;
  }

  .renderInline {
    margin-left: 0.125rem;
    display: inline;
  }

  :global(.renderInline + .renderInline) {
    margin-left: -0.25rem;
    display: inline;
  }
</style>
