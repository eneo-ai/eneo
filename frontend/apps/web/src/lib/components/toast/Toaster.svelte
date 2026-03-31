<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { fly, fade } from "svelte/transition";
  import { cubicOut, backOut } from "svelte/easing";
  import { X, CheckCircle2, XCircle, Info, AlertTriangle } from "lucide-svelte";
  import { toasts, content, close, portal, type ToastType } from "./toastStore";

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
