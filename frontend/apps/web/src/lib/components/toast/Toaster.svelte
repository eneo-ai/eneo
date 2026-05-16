<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { onMount } from "svelte";
  import { fly, fade } from "svelte/transition";
  import { cubicOut, backOut } from "svelte/easing";
  import { X, CheckCircle2, XCircle, Info, AlertTriangle } from "lucide-svelte";
  import { toasts, content, close, portal, type ToastType } from "./toastStore";

  // `mounted` stays `false` on SSR and on the initial client render
  // (which is hydration), then flips to `true` after `onMount` runs.
  // Together with the `{#if mounted}` gate below this guarantees the
  // SSR HTML and the pre-portal client DOM both emit nothing at the
  // toaster source position, so Svelte's hydration walker sees a
  // matching shape and does not bail the layout subtree out.
  let mounted = $state(false);
  onMount(() => {
    mounted = true;
  });

  const icons: Record<ToastType, typeof CheckCircle2> = {
    success: CheckCircle2,
    error: XCircle,
    info: Info,
    warning: AlertTriangle
  };

  const styles: Record<ToastType, string> = {
    success: "bg-positive-dimmer border-positive-default/40 text-positive-stronger",
    error: "bg-negative-dimmer border-negative-default/40 text-negative-stronger",
    info: "bg-accent-dimmer border-accent-default/40 text-accent-stronger",
    warning: "bg-warning-dimmer border-warning-default/40 text-warning-stronger"
  };

  const iconStyles: Record<ToastType, string> = {
    success: "text-positive-default",
    error: "text-negative-default",
    info: "text-accent-default",
    warning: "text-warning-default"
  };
</script>

<!--
  The toast container is portal-mounted to `document.body` by melt-ui's
  `use:portal` action. On SSR the action does not run, so the SSR HTML
  keeps the div at its source position inside the layout subtree; on
  client the action mounts it to body. Svelte 5 treats this position
  drift as a hydration mismatch and bails out the whole layout subtree,
  which clears the page content area until the next client render
  catches up. A `browser`-only gate is not enough either, because the
  initial client render IS hydration — Svelte would see "client wants
  to render a div, SSR did not". Gating on a post-mount `mounted` flag
  keeps both SSR and initial-client-render emitting nothing at this
  source position, so hydration agrees; the portal then mounts the
  toast container to `document.body` after onMount fires.
  -->
{#if mounted}
  <div
    use:portal
    class="pointer-events-none fixed inset-0 z-[60] flex flex-col items-end gap-2.5 pt-16 pr-4 sm:pr-6"
    aria-live="polite"
    aria-label="Notifications"
  >
    <div class="ml-auto flex w-full max-w-sm flex-col items-end gap-2.5">
      {#each $toasts as { id, data } (id)}
        {@const Icon = icons[data.type]}
        {@const style = styles[data.type]}
        {@const iconStyle = iconStyles[data.type]}

        <div
          {...$content(id)}
          class="pointer-events-auto flex w-full items-start gap-2.5 rounded-lg border px-4 py-3.5 shadow-[0_4px_20px_-4px_rgba(0,0,0,0.15),0_2px_6px_-2px_rgba(0,0,0,0.1)] backdrop-blur-sm {style}"
          in:fly={{ y: -20, duration: 250, easing: backOut }}
          out:fade={{ duration: 150, easing: cubicOut }}
        >
          <Icon class="mt-0.5 h-[18px] w-[18px] flex-shrink-0 {iconStyle}" />

          <p class="flex-1 text-sm leading-snug font-medium tracking-[-0.01em]">
            {data.message}
          </p>

          <button
            {...$close(id)}
            class="-mr-1 flex-shrink-0 rounded-md p-1 opacity-50 transition-all duration-150 hover:bg-black/5 hover:opacity-100 focus:outline-none focus-visible:ring-1 focus-visible:ring-current/40"
            aria-label="Dismiss"
          >
            <X class="h-3.5 w-3.5" />
          </button>
        </div>
      {/each}
    </div>
  </div>
{/if}
