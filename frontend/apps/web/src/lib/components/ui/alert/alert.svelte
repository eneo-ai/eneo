<script lang="ts" module>
  import { type VariantProps, tv } from "tailwind-variants";

  export const alertVariants = tv({
    base: "border-border grid gap-0.5 rounded-lg border px-2.5 py-2 text-left text-sm has-data-[slot=alert-action]:relative has-data-[slot=alert-action]:pr-18 has-[>svg]:grid-cols-[auto_1fr] has-[>svg]:gap-x-2 *:[svg]:row-span-2 *:[svg]:translate-y-0.5 *:[svg]:text-current *:[svg:not([class*='size-'])]:size-4 group/alert relative w-full",
    variants: {
      variant: {
        default: "bg-card text-card-foreground",
        destructive:
          // `--color-destructive` is `--negative-default`, the fill step. As a
          // foreground on the card it measures 3.50:1 in dark, and the
          // description's /90 took it to 3.05:1, against a 4.5:1 bar. The
          // `-stronger` step is 7.37 light / 5.05 dark. The alpha is gone
          // because at /90 dark is still 4.31:1, and the title's font-semibold
          // already separates it from the description without costing contrast.
          "text-negative-stronger bg-card *:data-[slot=alert-description]:text-negative-stronger *:[svg]:text-current"
      }
    },
    defaultVariants: {
      variant: "default"
    }
  });

  export type AlertVariant = VariantProps<typeof alertVariants>["variant"];
</script>

<script lang="ts">
  import type { HTMLAttributes } from "svelte/elements";
  import { cn, type WithElementRef } from "$lib/utils.js";

  let {
    ref = $bindable(null),
    class: className,
    variant = "default",
    children,
    ...restProps
  }: WithElementRef<HTMLAttributes<HTMLDivElement>> & {
    variant?: AlertVariant;
  } = $props();
</script>

<div
  bind:this={ref}
  data-slot="alert"
  role="alert"
  class={cn(alertVariants({ variant }), className)}
  {...restProps}
>
  {@render children?.()}
</div>
