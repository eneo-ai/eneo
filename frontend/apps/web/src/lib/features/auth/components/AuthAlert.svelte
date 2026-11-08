<script lang="ts" module>
  export type AuthAlertTone = "success" | "warning" | "error" | "info";
</script>

<script lang="ts">
  import type { Snippet } from "svelte";
  import type { HTMLAttributes } from "svelte/elements";
  import CircleAlert from "@lucide/svelte/icons/circle-alert";
  import CircleCheck from "@lucide/svelte/icons/circle-check";
  import Info from "@lucide/svelte/icons/info";
  import TriangleAlert from "@lucide/svelte/icons/triangle-alert";
  import * as Alert from "$lib/components/ui/alert";
  import { cn } from "$lib/utils";

  const toneClasses: Record<AuthAlertTone, string> = {
    success: "border-positive-default/40 bg-positive-dimmer text-positive-stronger",
    warning: "border-warning-default/40 bg-warning-dimmer text-warning-stronger",
    error: "border-negative-default/40 bg-negative-dimmer text-negative-stronger",
    info: "border-default bg-secondary text-primary"
  };

  const toneIcons = {
    success: CircleCheck,
    warning: TriangleAlert,
    error: CircleAlert,
    info: Info
  };

  let {
    tone = "info",
    title,
    class: className,
    ref = $bindable(null),
    children,
    ...restProps
  }: HTMLAttributes<HTMLDivElement> & {
    tone?: AuthAlertTone;
    title?: string;
    ref?: HTMLDivElement | null;
    children: Snippet;
  } = $props();

  const Icon = $derived(toneIcons[tone]);
</script>

<!-- Errors interrupt; everything else is announced politely. -->
<Alert.Root
  bind:ref
  role={tone === "error" ? "alert" : "status"}
  class={cn("gap-1 px-4 py-3", toneClasses[tone], className)}
  {...restProps}
>
  <Icon aria-hidden="true" class="size-5" />
  {#if title}
    <Alert.Title>{title}</Alert.Title>
  {/if}
  <Alert.Description class="text-current [&_p:not(:last-child)]:mb-1.5">
    {@render children()}
  </Alert.Description>
</Alert.Root>
