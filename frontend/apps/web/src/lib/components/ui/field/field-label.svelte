<script lang="ts">
  import { Label } from "$lib/components/ui/label/index.js";
  import { cn } from "$lib/utils.js";
  import type { ComponentProps } from "svelte";

  let {
    ref = $bindable(null),
    class: className,
    children,
    ...restProps
  }: ComponentProps<typeof Label> = $props();
</script>

<Label
  bind:ref
  data-slot="field-label"
  class={cn(
    // NOTE: `has-data-[state=checked]:` instead of upstream's `has-data-checked:` because
    // bits-ui sets `data-state="checked"` on checkboxes/radios, not `data-checked`.
    // Also uses eneo accent tokens (`bg-accent-default`/`border-accent-default`) instead of
    // shadcn's `bg-primary` — see app.css `--color-primary` namespace conflict comment.
    "has-data-[state=checked]:bg-accent-default/5 has-data-[state=checked]:border-accent-default/30 dark:has-data-[state=checked]:border-accent-default/20 dark:has-data-[state=checked]:bg-accent-default/10 group/field-label peer/field-label flex w-fit gap-2 leading-snug group-data-[disabled=true]/field:opacity-50 has-[>[data-slot=field]]:rounded-lg has-[>[data-slot=field]]:border *:data-[slot=field]:p-2.5",
    "has-[>[data-slot=field]]:w-full has-[>[data-slot=field]]:flex-col",
    className
  )}
  {...restProps}
>
  {@render children?.()}
</Label>
