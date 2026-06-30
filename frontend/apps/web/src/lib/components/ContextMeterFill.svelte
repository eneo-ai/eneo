<script lang="ts">
  // Shared fill primitive for the context meters (ConfigContextMeter and
  // ContextUsageBar). Centralises the WCAG-driven minimum width and the 1px
  // track inset so the two bars render identically and can't drift apart.
  // A single bar is just a segment at leftPct 0.
  type Props = { leftPct?: number; widthPct: number; class?: string };
  const { leftPct = 0, widthPct, class: className = "" }: Props = $props();
</script>

<div
  class="absolute top-0 bottom-0 my-auto h-[calc(100%-2px)] rounded-full transition-all duration-300 ease-out {className}"
  style:left="{leftPct}%"
  style:width="max(3px, calc({widthPct}% - 2px))"
  style:margin-left="1px"
></div>
