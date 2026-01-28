<!--
  Copyright (c) 2026 Sundsvalls Kommun
-->
<script lang="ts">
  import { m } from "$lib/paraglide/messages";
</script>

<div class="flex items-center gap-2" role="status" aria-label={m.assistant_is_typing()}>
  <span class="typing-dot"></span>
  <span class="typing-dot" style="animation-delay: 700ms"></span>
</div>

<style lang="postcss">
  @reference "@intric/ui/styles";

  @keyframes typing-breathe {
    0%,
    100% {
      transform: scale(1) translateX(0);
      opacity: 0.5;
    }
    50% {
      transform: scale(1.15) translateX(2px);
      opacity: 1;
    }
  }

  .typing-dot {
    @apply bg-accent-stronger h-2 w-2 rounded-full;
    animation: typing-breathe 1.4s ease-in-out infinite;
  }

  @media (prefers-reduced-motion: reduce) {
    .typing-dot {
      animation: none;
      opacity: 0.7;
    }
  }
</style>
