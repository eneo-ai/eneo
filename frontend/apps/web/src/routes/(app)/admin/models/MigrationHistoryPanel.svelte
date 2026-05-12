<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Read-only history of completion-model migrations. Each row expands to show
  per-entity-type counts, warnings, and any error message — driven by an
  expander button rather than a click-anywhere row so keyboard navigation
  works without custom key handlers.
-->

<script lang="ts">
  import { onMount } from "svelte";
  import { Loader2, ChevronDown, AlertTriangle } from "lucide-svelte";

  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";

  import * as Table from "$lib/components/ui/table/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";

  import { migrationHistoryRefreshVersion } from "./migrationHistoryRefresh";
  import { translateMigrationWarning } from "./migrationWarnings";

  type MigrationRecord = {
    id: string;
    from_model_id: string | null;
    from_model_name: string;
    to_model_id: string | null;
    to_model_name: string;
    migrated_count: number;
    status: string;
    initiated_by_id: string;
    initiated_by_name: string;
    started_at: string | null;
    completed_at: string | null;
    duration: number | null;
    error_message: string | null;
    migration_details: Record<string, number> | null;
    warnings: string[] | null;
  };

  type StatusVariant = "default" | "secondary" | "destructive" | "outline";

  const intric = getIntric();

  let history = $state<MigrationRecord[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let lastLoadedVersion = 0;
  let expandedId = $state<string | null>(null);

  async function loadHistory() {
    loading = true;
    error = null;
    try {
      const result = await intric.models.getAllMigrationHistory();
      history = result as MigrationRecord[];
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : m.migration_history_load_failed();
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    lastLoadedVersion = $migrationHistoryRefreshVersion;
    void loadHistory();
  });

  $effect(() => {
    if ($migrationHistoryRefreshVersion !== lastLoadedVersion) {
      lastLoadedVersion = $migrationHistoryRefreshVersion;
      void loadHistory();
    }
  });

  function toggleExpand(id: string) {
    expandedId = expandedId === id ? null : id;
  }

  function formatDate(dateStr: string | null): string {
    if (!dateStr) return "–";
    const date = new Date(dateStr);
    return date.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    });
  }

  function formatDuration(seconds: number | null): string {
    if (!seconds) return "–";
    if (seconds < 1) return `${Math.round(seconds * 1000)}ms`;
    return `${seconds.toFixed(1)}s`;
  }

  function statusVariant(status: string): StatusVariant {
    switch (status) {
      case "completed":
        return "outline";
      case "failed":
        return "destructive";
      case "in_progress":
        return "secondary";
      default:
        return "secondary";
    }
  }

  // Map backend status strings to localised labels. Unknown values fall
  // back to the raw key so a future backend addition doesn't render as
  // an empty badge — operators still see something actionable.
  function statusLabel(status: string): string {
    switch (status) {
      case "completed":
        return m.migration_status_completed();
      case "failed":
        return m.migration_status_failed();
      case "in_progress":
        return m.migration_status_in_progress();
      default:
        return status;
    }
  }

  // Localised labels for the per-entity-type counts in the expanded row.
  // Falls back to the raw key if a backend addition hasn't been translated yet.
  const detailLabels: Record<string, string> = $derived({
    assistants: m.migration_detail_assistants(),
    apps: m.migration_detail_apps(),
    services: m.migration_detail_services(),
    questions: m.migration_detail_questions(),
    spaces: m.migration_detail_spaces(),
    assistant_templates: m.migration_detail_assistant_templates(),
    app_templates: m.migration_detail_app_templates()
  });
</script>

<div class="flex flex-col gap-4 p-4">
  {#if loading}
    <div class="text-muted flex items-center justify-center py-12">
      <Loader2 class="mr-2 size-5 animate-spin" aria-hidden="true" />
      <span>{m.loading()}</span>
    </div>
  {:else if error}
    <div
      class="border-destructive bg-destructive/10 text-destructive border-l-2 px-4 py-3 text-sm"
      role="alert"
    >
      {error}
    </div>
  {:else if history.length === 0}
    <div class="text-muted flex items-center justify-center py-12">
      <span>{m.migration_history_empty()}</span>
    </div>
  {:else}
    <Table.Root>
      <Table.Header>
        <Table.Row>
          <Table.Head class="w-[1%]">
            <span class="sr-only">{m.migration_history_expand()}</span>
          </Table.Head>
          <Table.Head>{m.migration_history_date()}</Table.Head>
          <Table.Head>{m.migration_history_from()}</Table.Head>
          <Table.Head>{m.migration_history_to()}</Table.Head>
          <Table.Head class="text-right">{m.migration_history_count()}</Table.Head>
          <Table.Head>{m.migration_history_by()}</Table.Head>
          <Table.Head>{m.migration_history_status()}</Table.Head>
        </Table.Row>
      </Table.Header>

      <Table.Body>
        {#each history as record (record.id)}
          {@const isExpanded = expandedId === record.id}

          <Table.Row>
            <Table.Cell>
              <Button
                variant="ghost"
                size="icon-xs"
                aria-expanded={isExpanded}
                aria-controls="migration-detail-{record.id}"
                aria-label={isExpanded
                  ? m.migration_history_collapse()
                  : m.migration_history_expand()}
                onclick={() => toggleExpand(record.id)}
              >
                <ChevronDown
                  class="transition-transform {isExpanded ? 'rotate-0' : '-rotate-90'}"
                  aria-hidden="true"
                />
              </Button>
            </Table.Cell>
            <Table.Cell class="text-muted whitespace-nowrap">
              {formatDate(record.completed_at ?? record.started_at)}
            </Table.Cell>
            <Table.Cell>{record.from_model_name}</Table.Cell>
            <Table.Cell>{record.to_model_name}</Table.Cell>
            <Table.Cell class="text-right tabular-nums">{record.migrated_count}</Table.Cell>
            <Table.Cell class="text-muted">{record.initiated_by_name}</Table.Cell>
            <Table.Cell>
              <Badge variant={statusVariant(record.status)}>{statusLabel(record.status)}</Badge>
            </Table.Cell>
          </Table.Row>

          {#if isExpanded}
            <Table.Row id="migration-detail-{record.id}">
              <Table.Cell colspan={7} class="bg-muted/40 p-0">
                <div class="px-8 py-4">
                  <dl class="grid max-w-lg grid-cols-[max-content_1fr] gap-x-6 gap-y-1.5 text-sm">
                    <dt class="text-muted whitespace-nowrap">
                      {m.migration_history_duration()}
                    </dt>
                    <dd class="font-mono text-xs">{formatDuration(record.duration)}</dd>

                    {#if record.migration_details}
                      {#each Object.entries(record.migration_details).filter(([k, v]) => k !== "total" && v > 0) as [type, count] (type)}
                        <dt class="text-muted whitespace-nowrap">
                          {detailLabels[type] ?? type}
                        </dt>
                        <dd class="tabular-nums">{count}</dd>
                      {/each}
                    {/if}
                  </dl>

                  {#if record.warnings && record.warnings.length > 0}
                    <div class="border-border mt-3 border-t pt-3">
                      <div class="text-muted mb-1.5 flex items-center gap-1.5 text-sm">
                        <AlertTriangle class="size-3.5" aria-hidden="true" />
                        <span>{m.migration_history_warnings()}</span>
                      </div>
                      <ul class="text-warning-stronger space-y-1 pl-5 text-sm">
                        {#each record.warnings as w, i (i)}
                          <li>{translateMigrationWarning(w)}</li>
                        {/each}
                      </ul>
                    </div>
                  {/if}

                  {#if record.error_message}
                    <div class="text-destructive border-border mt-3 border-t pt-3 text-sm">
                      {record.error_message}
                    </div>
                  {/if}
                </div>
              </Table.Cell>
            </Table.Row>
          {/if}
        {/each}
      </Table.Body>
    </Table.Root>
  {/if}
</div>
