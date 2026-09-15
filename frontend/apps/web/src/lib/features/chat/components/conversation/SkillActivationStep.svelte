<!--
  Copyright (c) 2026 Sundsvalls Kommun

  A Skill the model loaded for this reply, shown as a visible pill above the
  answer so the reader can tell which Skill shaped it. The activation resolves
  inside the stream and arrives already complete, so instead of a running
  state the pill gets one quiet entrance when it lands live: it rises in and
  the icon settles from the accent to the resting colour. Reloaded history
  renders still. Click expands to the Skill's mode and what it meant for the
  reply, in plain words rather than the raw activation payload.
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { BookOpenCheck, ChevronRight, X } from "lucide-svelte";
  import { slide } from "svelte/transition";
  import { Badge } from "$lib/components/ui/badge/index.js";

  type Status = "preparing" | "running" | "complete" | "failed" | "denied";

  let {
    name,
    status,
    args,
    live = false
  }: {
    /** The Skill's display name. */
    name: string;
    status: Status;
    /** Step arguments from the backend: `mode` (always | on_demand) and, for a rejected activation, `reason`. */
    args?: Record<string, unknown>;
    /** The step arrived during the turn being streamed right now. */
    live?: boolean;
  } = $props();

  let open = $state(false);
  const failed = $derived(status === "failed" || status === "denied");
  const label = $derived(
    failed ? m.tool_activate_skill_failed({ name }) : m.skill_used_in_reply({ name })
  );
  const always = $derived(args?.mode === "always");
  // Rejection reasons share the debug panel's wording so the two never drift.
  const reasonLabels: Record<string, () => string> = {
    unknown_key: m.chat_debug_rejection_unknown_key,
    blocked: m.chat_debug_rejection_blocked,
    activation_unavailable: m.chat_debug_rejection_activation_unavailable,
    activation_limit_exceeded: m.chat_debug_rejection_activation_limit_exceeded,
    context_limit_exceeded: m.chat_debug_rejection_context_limit_exceeded,
    model_context_limit_exceeded: m.chat_debug_rejection_model_context_limit_exceeded,
    token_measurement_unavailable: m.chat_debug_rejection_token_measurement_unavailable,
    reserved_tool_collision: m.chat_debug_rejection_reserved_tool_collision
  };
  const detail = $derived.by(() => {
    if (failed) {
      const reason = typeof args?.reason === "string" ? reasonLabels[args.reason]?.() : undefined;
      return reason ?? m.skill_step_failed_detail();
    }
    return always ? m.skill_step_always_detail() : m.skill_step_on_demand_detail();
  });
</script>

<div class={live ? "step-enter" : undefined}>
  <button
    type="button"
    class="group inline-flex max-w-full cursor-pointer items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs font-medium transition-colors focus-visible:ring-2 focus-visible:ring-offset-1 focus-visible:outline-none {failed
      ? 'border-negative-default/30 bg-negative-dimmer text-negative-default hover:border-negative-default/50'
      : 'border-accent-default/30 bg-accent-dimmer text-accent-stronger hover:border-accent-default/50'}"
    onclick={() => (open = !open)}
    aria-expanded={open}
  >
    {#if failed}
      <X class="h-3.5 w-3.5 shrink-0" aria-hidden="true" />
    {:else}
      <BookOpenCheck class="h-3.5 w-3.5 shrink-0 {live ? 'icon-settle' : ''}" aria-hidden="true" />
    {/if}
    <span class="truncate">{label}</span>
    <ChevronRight
      class="h-3 w-3 shrink-0 opacity-60 transition-transform {open ? 'rotate-90' : ''}"
      aria-hidden="true"
    />
  </button>

  {#if open}
    <div
      transition:slide={{ duration: 160 }}
      class="border-border bg-secondary/40 mt-1.5 mb-1 flex max-w-prose flex-col gap-1.5 rounded-lg border px-3 py-2.5 text-sm"
    >
      <div class="flex flex-wrap items-center gap-2">
        <span class="font-medium">{name}</span>
        {#if failed}
          <Badge variant="destructive">{m.chat_tool_status_failed()}</Badge>
        {:else}
          <Badge variant="outline">
            {always ? m.skills_activation_mode_always() : m.skills_activation_mode_on_demand()}
          </Badge>
        {/if}
      </div>
      <p class="text-muted-foreground text-[13px] leading-5">{detail}</p>
    </div>
  {/if}
</div>

<style lang="postcss">
  /* One quiet moment per activation, in CSS so reduced-motion users get the
     finished state directly. */
  .step-enter {
    animation: step-enter 240ms cubic-bezier(0.16, 1, 0.3, 1) both;
  }

  :global(.icon-settle) {
    animation: icon-settle 1.6s cubic-bezier(0.16, 1, 0.3, 1) both;
  }

  @keyframes step-enter {
    from {
      opacity: 0;
      transform: translateY(4px);
    }
    to {
      opacity: 1;
      transform: none;
    }
  }

  @keyframes icon-settle {
    0% {
      color: var(--accent-default);
      transform: scale(0.85);
    }
    25% {
      transform: scale(1.15);
    }
    45% {
      color: var(--accent-default);
      transform: none;
    }
    100% {
      color: currentColor;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .step-enter,
    :global(.icon-settle) {
      animation: none;
    }
  }
</style>
