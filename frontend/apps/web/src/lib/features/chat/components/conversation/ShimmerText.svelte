<!--
  Copyright (c) 2026 Sundsvalls Kommun

  Text with a sweeping gradient highlight, for inline loading states
  ("Söker kunskap…"). Svelte port of the AI Elements / AI SDK Shimmer
  component: muted base text with a brighter band clipped to the glyphs via
  background-clip, sweeping left to right on an infinite linear loop. The
  gradient spread scales with the text length, mirroring the original.
-->
<script lang="ts">
  let {
    text,
    duration = 2
  }: {
    text: string;
    /** One full sweep, in seconds. */
    duration?: number;
  } = $props();

  const spreadPx = $derived(Math.max(24, text.length * 2));
</script>

<span class="shimmer-text" style="--shimmer-duration: {duration}s; --shimmer-spread: {spreadPx}px"
  >{text}</span
>

<style lang="postcss">
  .shimmer-text {
    display: inline-block;
    color: transparent;
    background-image:
      linear-gradient(
        90deg,
        transparent calc(50% - var(--shimmer-spread)),
        var(--text-primary) 50%,
        transparent calc(50% + var(--shimmer-spread))
      ),
      linear-gradient(var(--text-muted), var(--text-muted));
    background-size:
      250% 100%,
      auto;
    background-repeat: no-repeat, padding-box;
    -webkit-background-clip: text;
    background-clip: text;
    animation: shimmer-sweep var(--shimmer-duration) linear infinite;
  }

  @keyframes shimmer-sweep {
    0% {
      background-position: 100% center;
    }
    100% {
      background-position: 0% center;
    }
  }

  @media (prefers-reduced-motion: reduce) {
    .shimmer-text {
      animation: none;
      background: none;
      color: var(--text-muted);
    }
  }
</style>
