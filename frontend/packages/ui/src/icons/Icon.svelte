<script lang="ts">
  // These are the props that will be typed on imported icons
  type IconProps = {
    size?: "sm" | "md" | "lg";
  };

  export let size = "md";
  export let src = "";

  /* eslint-disable @typescript-eslint/no-unused-vars */
  type $$Props = {
    src: string;
  } & IconProps;
</script>

<!-- The `icon-size-*` class contains "size-" on purpose: shadcn buttons and menus resize descendant
     svgs unless their class has "size-", and these icons should keep their own default size there. -->
<svg
  xmlns="http://www.w3.org/2000/svg"
  fill="none"
  stroke="currentColor"
  viewBox="0 0 24 24"
  stroke-width="1.5"
  data-size={size}
  {...$$restProps}
  class="icon-size-{size} {$$restProps.class ?? ''}"
>
  <!-- eslint-disable svelte/no-at-html-tags -->
  {@html src}
</svg>

<style>
  /* Layered so size utilities on an icon (`size-4`, `h-4 w-4`) win over these defaults. */
  @layer base {
    svg[data-size="sm"] {
      height: 1.2rem;
      width: 1.2rem;
      flex-shrink: 0;
    }

    svg[data-size="md"] {
      height: 1.5rem;
      width: 1.5rem;
      flex-shrink: 0;
    }

    svg[data-size="lg"] {
      height: 6rem;
      width: 6rem;
      stroke-width: 1;
    }
  }
</style>
