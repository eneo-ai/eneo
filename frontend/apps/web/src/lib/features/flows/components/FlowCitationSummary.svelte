<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import type { FlowCitationSummary } from "./flowCitationSummary";

  let {
    summary,
    title = m.flow_citation_summary_title()
  }: {
    summary: FlowCitationSummary;
    title?: string;
  } = $props();

  const statusLine = $derived.by(() => {
    switch (summary.status) {
      case "observed":
        return m.flow_citation_status_observed({
          count: String(summary.matched_cited_source_count)
        });
      case "missing_required_citations":
        return m.flow_citation_status_missing();
      case "unknown_citation_ids_present":
        return m.flow_citation_status_unknown();
      case "citations_on_without_sources":
        return m.flow_citation_status_no_sources();
      case "unavailable":
        return m.flow_citation_status_unavailable();
    }
  });

  const isWarning = $derived(
    summary.status === "missing_required_citations" ||
      summary.status === "unknown_citation_ids_present"
  );
</script>

<section class="flex flex-col gap-1.5" aria-label={title}>
  <div class="flex flex-wrap items-center gap-2">
    <h4 class="text-secondary text-xs font-semibold">{title}</h4>
    <Badge
      variant="outline"
      class={isWarning
        ? "bg-warning-dimmer text-warning-stronger border-transparent text-xs"
        : "bg-secondary text-secondary border-transparent text-xs"}
    >
      {statusLine}
    </Badge>
  </div>

  {#if summary.stale_after_edit}
    <p class="text-muted text-xs leading-relaxed" role="note">
      {m.flow_citation_stale_after_edit()}
    </p>
  {/if}

  {#if summary.sources.length > 0}
    <ul class="flex list-none flex-col gap-1 p-0">
      {#each summary.sources as source, index (index)}
        <li class="text-primary flex items-baseline gap-1.5 text-xs">
          <span class="text-muted select-none" aria-hidden="true">•</span>
          {#if source.identity_resolved && (source.display_name || source.container_label)}
            <span class="min-w-0 truncate font-medium">
              {source.display_name ?? source.container_label}
            </span>
            {#if source.display_name && source.container_label}
              <span class="text-muted shrink-0">· {source.container_label}</span>
            {/if}
          {:else}
            <span class="text-muted italic">{m.flow_citation_source_unidentified()}</span>
          {/if}
        </li>
      {/each}
    </ul>
    {#if summary.sources_truncated}
      <p class="text-muted text-xs">
        {m.flow_citation_sources_truncated({
          shown: String(summary.sources.length),
          count: String(summary.matched_cited_source_count)
        })}
      </p>
    {/if}
  {/if}
</section>
