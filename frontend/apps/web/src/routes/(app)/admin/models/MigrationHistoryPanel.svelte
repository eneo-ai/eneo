<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { onMount } from "svelte";
  import { Label } from "@intric/ui";
  import { Loader2, ChevronDown, AlertTriangle } from "lucide-svelte";
  import { migrationHistoryRefreshVersion } from "./migrationHistoryRefresh";
  import { translateMigrationWarning } from "./migrationWarnings";

  const intric = getIntric();

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

  let history: MigrationRecord[] = [];
  let loading = true;
  let error: string | null = null;
  let lastLoadedVersion = 0;
  let expandedId: string | null = null;

  async function loadHistory() {
    loading = true;
    error = null;
    try {
      const result = await intric.models.getAllMigrationHistory();
      history = result as MigrationRecord[];
    } catch (e: unknown) {
      error = e instanceof Error ? e.message : "Failed to load migration history";
    } finally {
      loading = false;
    }
  }

  onMount(() => {
    lastLoadedVersion = $migrationHistoryRefreshVersion;
    void loadHistory();
  });

  $: if ($migrationHistoryRefreshVersion !== lastLoadedVersion) {
    lastLoadedVersion = $migrationHistoryRefreshVersion;
    void loadHistory();
  }

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

  function statusColor(status: string): Label.LabelColor {
    switch (status) {
      case "completed":
        return "green";
      case "failed":
        return "red";
      case "in_progress":
        return "yellow";
      default:
        return "gray";
    }
  }

  // Localised labels for the per-entity-type counts in the expanded row.
  // Falls back to the raw key if a backend addition hasn't been translated yet.
  const detailLabels = {
    assistants: m.migration_detail_assistants(),
    apps: m.migration_detail_apps(),
    services: m.migration_detail_services(),
    questions: m.migration_detail_questions(),
    spaces: m.migration_detail_spaces(),
    assistant_templates: m.migration_detail_assistant_templates(),
    app_templates: m.migration_detail_app_templates()
  } as Record<string, string>;
</script>

<div class="flex flex-col gap-4 p-4">
  {#if loading}
    <div class="text-muted flex items-center justify-center py-12">
      <Loader2 class="mr-2 h-5 w-5 animate-spin" />
      <span>{m.loading()}</span>
    </div>
  {:else if error}
    <div
      class="border-negative-default bg-negative-dimmer/50 text-negative-default border-l-2 px-4 py-3 text-sm"
    >
      {error}
    </div>
  {:else if history.length === 0}
    <div class="text-muted flex items-center justify-center py-12">
      <span>{m.migration_history_empty()}</span>
    </div>
  {:else}
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-default text-muted border-b text-left">
            <th class="w-[1%] px-3 py-2 font-medium"></th>
            <th class="px-3 py-2 font-medium">{m.migration_history_date()}</th>
            <th class="px-3 py-2 font-medium">{m.migration_history_from()}</th>
            <th class="px-3 py-2 font-medium">{m.migration_history_to()}</th>
            <th class="px-3 py-2 text-right font-medium">{m.migration_history_count()}</th>
            <th class="px-3 py-2 font-medium">{m.migration_history_by()}</th>
            <th class="px-3 py-2 font-medium">{m.migration_history_status()}</th>
          </tr>
        </thead>
        <tbody>
          {#each history as record (record.id)}
            <tr
              class="border-dimmer hover:bg-hover-dimmer cursor-pointer border-b transition-colors"
              on:click={() => toggleExpand(record.id)}
            >
              <td class="px-3 py-2">
                <ChevronDown
                  size={14}
                  class="text-muted transition-transform {expandedId === record.id
                    ? 'rotate-0'
                    : '-rotate-90'}"
                />
              </td>
              <td class="text-muted px-3 py-2 whitespace-nowrap">
                {formatDate(record.completed_at ?? record.started_at)}
              </td>
              <td class="px-3 py-2">{record.from_model_name}</td>
              <td class="px-3 py-2">{record.to_model_name}</td>
              <td class="px-3 py-2 text-right tabular-nums">{record.migrated_count}</td>
              <td class="text-muted px-3 py-2">{record.initiated_by_name}</td>
              <td class="px-3 py-2">
                <Label.Single
                  item={{
                    label: record.status,
                    color: statusColor(record.status)
                  }}
                />
              </td>
            </tr>

            <!-- Expanded detail row -->
            {#if expandedId === record.id}
              <tr>
                <td colspan="8" class="px-0 py-0">
                  <div class="bg-surface-dimmer/40 border-dimmer border-b px-8 py-4">
                    <table class="w-full max-w-lg text-sm">
                      <tbody>
                        <tr>
                          <td class="text-muted py-1.5 pr-6 whitespace-nowrap"
                            >{m.migration_history_duration()}</td
                          >
                          <td class="py-1.5 font-mono text-xs">{formatDuration(record.duration)}</td
                          >
                        </tr>
                        {#if record.migration_details}
                          {#each Object.entries(record.migration_details).filter(([k, v]) => k !== "total" && v > 0) as [type, count] (type)}
                            <tr>
                              <td class="text-muted py-1.5 pr-6 whitespace-nowrap"
                                >{detailLabels[type] ?? type}</td
                              >
                              <td class="py-1.5 tabular-nums">{count}</td>
                            </tr>
                          {/each}
                        {/if}
                      </tbody>
                    </table>

                    {#if record.warnings && record.warnings.length > 0}
                      <div class="border-dimmer mt-3 border-t pt-3">
                        <div class="text-muted mb-1.5 flex items-center gap-1.5 text-sm">
                          <AlertTriangle size={13} />
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
                      <div class="border-dimmer text-negative-default mt-3 border-t pt-3 text-sm">
                        {record.error_message}
                      </div>
                    {/if}
                  </div>
                </td>
              </tr>
            {/if}
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
