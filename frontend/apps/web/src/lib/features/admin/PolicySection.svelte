<!--
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
-->

<!--
  Shared shell for the governance policy sections (models, MCP, prompt).
  Owns the card frame, the icon tile, the heading + status badge and the
  divider so the three sections stay visually identical and there is a single
  place to evolve that layout. Section-specific content goes in the default
  slot; the section-specific icon goes in the `icon` snippet.
-->
<script lang="ts">
  import type { Snippet } from "svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";

  type Props = {
    /** Stable key used to build the aria ids (`section-{id}-title` / `-summary`). */
    id: string;
    title: string;
    description: string;
    /** Short status text shown in the badge next to the title. */
    summary: string;
    summaryVariant: "default" | "outline" | "destructive";
    icon: Snippet;
    children: Snippet;
  };

  let { id, title, description, summary, summaryVariant, icon, children }: Props = $props();
</script>

<section
  aria-labelledby={`section-${id}-title`}
  aria-describedby={`section-${id}-summary`}
  class="border-default bg-card overflow-hidden rounded-xl border"
>
  <header class="border-default flex items-start gap-4 border-b p-5">
    <div
      class="bg-secondary text-primary flex h-10 w-10 shrink-0 items-center justify-center rounded-lg"
      aria-hidden="true"
    >
      {@render icon()}
    </div>
    <div class="min-w-0 flex-1">
      <div class="flex flex-wrap items-center gap-2">
        <h2 id={`section-${id}-title`} class="text-primary text-base font-semibold">
          {title}
        </h2>
        <Badge id={`section-${id}-summary`} variant={summaryVariant}>
          {summary}
        </Badge>
      </div>
      <p class="text-secondary mt-1 text-sm">
        {description}
      </p>
    </div>
  </header>
  <div class="space-y-4 p-5">
    {@render children()}
  </div>
</section>
