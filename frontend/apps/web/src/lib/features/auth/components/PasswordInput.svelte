<script lang="ts">
  import type { HTMLInputAttributes } from "svelte/elements";
  import { Eye, EyeOff } from "lucide-svelte";
  import { Input } from "$lib/components/ui/input";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils";

  let {
    value = $bindable(""),
    ref = $bindable(null),
    class: className,
    disabled,
    ...restProps
  }: Omit<HTMLInputAttributes, "type" | "value" | "files"> & {
    value?: string;
    ref?: HTMLInputElement | null;
  } = $props();

  let visible = $state(false);
</script>

<div class="relative">
  <Input
    bind:ref
    bind:value
    type={visible ? "text" : "password"}
    class={cn("pr-10", className)}
    {disabled}
    {...restProps}
  />
  <button
    type="button"
    class="text-muted hover:text-default focus-visible:ring-ring absolute top-1/2 right-1 flex size-7 -translate-y-1/2 items-center justify-center rounded-md outline-none focus-visible:ring-2 disabled:pointer-events-none disabled:opacity-50"
    aria-label={visible ? m.hide_password() : m.show_password()}
    aria-pressed={visible}
    onclick={() => (visible = !visible)}
    {disabled}
  >
    {#if visible}
      <EyeOff aria-hidden="true" class="size-4" />
    {:else}
      <Eye aria-hidden="true" class="size-4" />
    {/if}
  </button>
</div>
