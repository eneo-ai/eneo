<script lang="ts">
  import { AlertDialog as AlertDialogPrimitive } from "bits-ui";
  import {
    buttonVariants,
    type ButtonVariant,
    type ButtonSize
  } from "$lib/components/ui/button/index.js";
  import { cn } from "$lib/utils.js";

  let {
    ref = $bindable(null),
    class: className,
    variant = "outline",
    size = "default",
    type = "button",
    ...restProps
  }: AlertDialogPrimitive.CancelProps & {
    variant?: ButtonVariant;
    size?: ButtonSize;
  } = $props();
</script>

<!-- NOTE: defaults to type="button" (upstream sets none) so Cancel never submits a surrounding form. -->
<AlertDialogPrimitive.Cancel
  bind:ref
  {type}
  data-slot="alert-dialog-cancel"
  class={cn(buttonVariants({ variant, size }), "cn-alert-dialog-cancel", className)}
  {...restProps}
/>
