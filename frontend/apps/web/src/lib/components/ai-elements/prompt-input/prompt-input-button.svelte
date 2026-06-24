<script lang="ts">
  import { Button, type ButtonProps } from "$lib/components/ui/button/index.js";
  import { cn } from "$lib/utils.js";

  let {
    variant = "ghost",
    size = "sm",
    type = "button",
    class: className,
    children,
    ...restProps
  }: ButtonProps = $props();
</script>

<Button
  data-slot="prompt-input-button"
  {variant}
  {size}
  {type}
  class={cn("h-9 gap-1.5 rounded-lg", className)}
  {...restProps}
>
  {@render children?.()}
</Button>
