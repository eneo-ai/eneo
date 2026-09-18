<script lang="ts">
  import { Checkbox as CheckboxPrimitive } from "bits-ui";
  import { cn, type WithoutChildrenOrChild } from "$lib/utils.js";
  import CheckIcon from "@lucide/svelte/icons/check";
  import MinusIcon from "@lucide/svelte/icons/minus";

  let {
    ref = $bindable(null),
    checked = $bindable(false),
    indeterminate = $bindable(false),
    class: className,
    ...restProps
  }: WithoutChildrenOrChild<CheckboxPrimitive.RootProps> = $props();
</script>

<CheckboxPrimitive.Root
  bind:ref
  data-slot="checkbox"
  class={cn(
    // NOTE: checked state uses `bg-accent-default` / `text-on-fill` / `border-accent-default`
    // instead of upstream's `bg-primary` / `text-primary-foreground` / `border-primary` —
    // see app.css `--color-primary` namespace conflict comment for the full rationale.
    "border-input data-[state=checked]:bg-accent-default data-[state=checked]:text-on-fill aria-invalid:aria-checked:border-accent-default focus-visible:border-ring focus-visible:ring-ring peer relative flex size-4 shrink-0 items-center justify-center rounded-[4px] border bg-(--control-checkbox-fill) transition-colors outline-none group-has-disabled/field:opacity-50 after:absolute after:-inset-x-3 after:-inset-y-2 focus-visible:ring-3 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-(--control-checkbox-invalid-border) aria-invalid:ring-3 aria-invalid:ring-(--control-checkbox-invalid-ring) data-[state=checked]:border-(--control-checkbox-checked-border)",
    className
  )}
  bind:checked
  bind:indeterminate
  {...restProps}
>
  {#snippet children({ checked, indeterminate })}
    <div
      data-slot="checkbox-indicator"
      class="grid place-content-center text-current transition-none [&>svg]:size-3.5"
    >
      {#if checked}
        <CheckIcon />
      {:else if indeterminate}
        <MinusIcon />
      {/if}
    </div>
  {/snippet}
</CheckboxPrimitive.Root>
