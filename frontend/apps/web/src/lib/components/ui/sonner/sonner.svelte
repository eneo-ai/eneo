<script lang="ts">
  import { onMount } from "svelte";
  import { Toaster as Sonner, type ToasterProps as SonnerProps } from "svelte-sonner";
  import { mode } from "mode-watcher";
  import Loader2Icon from "@lucide/svelte/icons/loader-2";
  import CircleCheckIcon from "@lucide/svelte/icons/circle-check";
  import OctagonXIcon from "@lucide/svelte/icons/octagon-x";
  import InfoIcon from "@lucide/svelte/icons/info";
  import TriangleAlertIcon from "@lucide/svelte/icons/triangle-alert";

  let { ...restProps }: SonnerProps = $props();

  // `mode.current` from mode-watcher is undefined during SSR and resolves
  // to the prefers-color-scheme / localStorage value on the client. If
  // `<Sonner theme={mode.current}>` renders during hydration the SSR and
  // client outputs disagree on the rendered theme attribute (Svelte 5
  // bails the layout subtree out). Gating the toaster on a post-mount
  // flag keeps both renders empty during hydration and lets the toaster
  // mount + theme-resolve cleanly afterward.
  let mounted = $state(false);
  onMount(() => {
    mounted = true;
  });
</script>

{#if mounted}
  <Sonner
    theme={mode.current}
    class="toaster group"
    style="--normal-bg: var(--color-popover); --normal-text: var(--color-popover-foreground); --normal-border: var(--color-border);"
    {...restProps}
  >
    {#snippet loadingIcon()}
      <Loader2Icon class="size-4 animate-spin" />
    {/snippet}
    {#snippet successIcon()}
      <CircleCheckIcon class="size-4" />
    {/snippet}
    {#snippet errorIcon()}
      <OctagonXIcon class="size-4" />
    {/snippet}
    {#snippet infoIcon()}
      <InfoIcon class="size-4" />
    {/snippet}
    {#snippet warningIcon()}
      <TriangleAlertIcon class="size-4" />
    {/snippet}
  </Sonner>
{/if}
