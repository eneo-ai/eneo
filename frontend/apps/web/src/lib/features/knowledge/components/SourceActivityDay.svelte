<script lang="ts">
  import type { Snippet } from "svelte";
  import { formatDateMedium } from "$lib/core/formatting/dateTime";
  import { m } from "$lib/paraglide/messages";

  let { date, children }: { date: string | null | undefined; children: Snippet } = $props();
  const headingId = $props.id();
</script>

<section aria-labelledby={headingId} class="flex flex-col">
  <h2 id={headingId} class="text-secondary pb-2 text-xs font-semibold tracking-wide uppercase">
    {formatDateMedium(date) || m.not_available()}
  </h2>
  <ol class="flex flex-col">
    {@render children()}
  </ol>
</section>
