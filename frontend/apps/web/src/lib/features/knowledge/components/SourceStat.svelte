<script lang="ts">
  import type { Snippet } from "svelte";

  let {
    label,
    tone = "number",
    children
  }: {
    label: string;
    /** Counts read large; dates, states and notes read as text. */
    tone?: "number" | "text";
    children: Snippet;
  } = $props();
</script>

<div class="bg-primary flex flex-col gap-1 px-4 py-3">
  <dt class="text-secondary text-xs">{label}</dt>
  <dd
    class={tone === "number"
      ? "text-xl font-semibold tabular-nums"
      : "flex flex-col gap-0.5 pt-1 text-sm font-semibold"}
  >
    {@render children()}
  </dd>
</div>
