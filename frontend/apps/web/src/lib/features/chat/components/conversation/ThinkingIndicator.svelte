<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Thinking indicator component for reasoning models.
  Displays a slower, more contemplative animation than the regular typing indicator.
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";
</script>

<div class="thinking-badge" role="status" aria-label={m.assistant_is_thinking()}>
  <span class="thinking-dots" aria-hidden="true">
    <span class="thinking-dot"></span>
    <span class="thinking-dot"></span>
    <span class="thinking-dot"></span>
  </span>
  <span class="thinking-text">{m.thinking()}</span>
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";

  .thinking-badge {
    @apply bg-accent-dimmer text-accent-stronger relative overflow-hidden rounded-full;
    display: inline-flex;
    align-items: center;
    gap: 0.5rem;
    padding: 0.5rem 0.875rem;
    width: fit-content;
    isolation: isolate;
  }

  .thinking-dots {
    display: flex;
    align-items: center;
    gap: 4px;
  }

  .thinking-dot {
    width: 4px;
    height: 4px;
    border-radius: 50%;
    background: currentColor;
    opacity: 0.35;
    animation: thinking-pulse 1.8s ease-in-out infinite;
  }

  .thinking-dot:nth-child(2) {
    animation-delay: 0.15s;
  }

  .thinking-dot:nth-child(3) {
    animation-delay: 0.3s;
  }

  @keyframes thinking-pulse {
    0%,
    100% {
      opacity: 0.35;
      transform: scale(1);
    }
    50% {
      opacity: 0.9;
      transform: scale(1.1);
    }
  }

  .thinking-text {
    position: relative;
    z-index: 1;
    font-size: 0.8125rem;
    line-height: 1.2;
  }

  /* Flowing gradient underlay */
  .thinking-badge::before {
    content: "";
    position: absolute;
    inset: 0;
    background: linear-gradient(
      90deg,
      transparent 0%,
      oklch(from var(--accent-default) l c h / 0.12) 30%,
      oklch(from var(--accent-default) l c h / 0.2) 50%,
      oklch(from var(--accent-default) l c h / 0.12) 70%,
      transparent 100%
    );
    background-size: 200% 100%;
    animation: gradient-flow 4s ease-in-out infinite;
    border-radius: inherit;
    pointer-events: none;
  }

  /* Subtle border accent */
  .thinking-badge::after {
    content: "";
    position: absolute;
    inset: 0;
    border-radius: inherit;
    border: 1px solid oklch(from var(--accent-stronger) l c h / 0.15);
    animation: border-breathe 3s ease-in-out infinite;
    pointer-events: none;
  }

  @keyframes gradient-flow {
    0%,
    100% {
      background-position: 100% 0;
    }
    50% {
      background-position: 0% 0;
    }
  }

  @keyframes border-breathe {
    0%,
    100% {
      border-color: oklch(from var(--accent-stronger) l c h / 0.1);
    }
    50% {
      border-color: oklch(from var(--accent-stronger) l c h / 0.2);
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .thinking-dot,
    .thinking-badge::before,
    .thinking-badge::after {
      animation: none;
    }

    .thinking-dot {
      opacity: 0.6;
    }

    .thinking-badge::after {
      border-color: oklch(from var(--accent-stronger) l c h / 0.15);
    }
  }
</style>
