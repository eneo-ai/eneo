<script lang="ts">
  import type { Icon } from "@intric/icons";
  import type { ComponentType } from "svelte";
  import { cva } from "class-variance-authority";

  export let href: string;
  export let isActive: boolean;
  export let icon: Icon | ComponentType;
  export let label: string;

  const link = cva(
    [
      "relative",
      "flex",
      "gap-4",
      "px-[1.45rem]",
      "py-2.5",
      "hover:font-medium",
      "hover:tracking-normal",
      "hover:text-primary"
    ],
    {
      variants: {
        active: {
          true: ["bg-hover-dimmer", "hover:bg-hover-default", "font-medium"],
          false: ["hover:bg-hover-dimmer", "tracking-[0.008rem]", "text-secondary"]
        }
      }
    }
  );
</script>

<!-- eslint-disable svelte/no-navigation-without-resolve -- href is a typed prop passed from caller -->
<a class={link({ active: isActive })} aria-current={isActive ? "page" : undefined} {href}>
  {#if isActive}
    <div class="bg-dynamic-default absolute top-0 bottom-0 left-0 w-[4px] rounded-r-full"></div>
  {/if}
  <svelte:component this={icon} class="size-6" />
  <span>{label}</span>
  <slot />
</a>
<!-- eslint-enable svelte/no-navigation-without-resolve -->
