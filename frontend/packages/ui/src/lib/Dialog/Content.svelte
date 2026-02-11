<script lang="ts">
  import { fade, fly, scale } from "svelte/transition";
  import { getDialog } from "./ctx.js";
  import { cubicOut } from "svelte/easing";
  import { cva, cx } from "class-variance-authority";

  const {
    elements: { overlay, content, portalled },
    states: { open }
  } = getDialog();

  /** Maximum width of the dialog, defaults to small */
  export let width: "small" | "medium" | "large" | "dynamic" = "small";
  /** Render Dialog into a form element, useful for input validation */
  export let form = false;

  /** Additional classes to apply to the dialog */
  let className: string = "";
  export { className as class };

  const dialog = cva(
    [
      "dialog-shadow",
      "fixed",
      "inset-0",
      "z-[51]",
      "mt-auto",
      "flex",
      "h-fit",
      "max-h-[85vh]",
      "flex-col",
      "gap-2",
      "rounded-sm",
      "border-b-2",
      "border-strongest",
      "bg-secondary",
      "px-5",
      "py-3",
      "md:m-auto md:max-w-[90vw]"
    ],
    {
      variants: {
        width: {
          small: ["lg:max-w-[30vw]"],
          medium: ["lg:max-w-[50vw]"],
          large: ["lg:max-w-[80vw]"],
          dynamic: ["w-fit", "lg:max-w-[80vw]"]
        }
      }
    }
  );

  function dialogTransition(node: Element) {
    return document.documentElement.clientWidth < 768
      ? fly(node, { y: 600, duration: 200, easing: cubicOut })
      : scale(node, { start: 1.03, duration: 200, easing: cubicOut });
  }
</script>

{#if $open}
  <div {...$portalled} use:portalled>
    <div
      {...$overlay}
      use:overlay
      class="bg-overlay-default fixed inset-0 z-50 backdrop-blur-sm backdrop-saturate-[0.7]"
      in:fade={{ duration: 170, easing: cubicOut }}
      out:fade={{ duration: 230 }}
    ></div>

    <svelte:element
      this={form ? "form" : "div"}
      class={cx(dialog({ width }), className)}
      {...$content}
      transition:dialogTransition
      use:content
    >
      <slot />
    </svelte:element>
  </div>
{/if}

<style>
  /* Shadow pseudo-element inherits border-radius from parent */
  .dialog-shadow::before {
    content: "";
    position: absolute;
    inset: 0px;
    z-index: -10;
    mix-blend-mode: multiply;
    border-radius: inherit;
    box-shadow:
      0px 1px 5px 1px rgb(0, 0, 0, 0.2),
      0px 10px 20px 0px rgba(0, 0, 0, 0.1);
  }
</style>
