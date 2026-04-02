<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { onMount } from "svelte";
  import { Label } from "@intric/ui";
  import { Loader2, ChevronDown, AlertTriangle } from "lucide-svelte";
  import { migrationHistoryRefreshVersion } from "./migrationHistoryRefresh";

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
    } catch (e: any) {
      error = e.message || "Failed to load migration history";
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
      case "completed": return "green";
      case "failed": return "red";
      case "in_progress": return "yellow";
      default: return "gray";
    }
  }

  const detailLabels: Record<string, string> = {
    assistants: "Assistenter",
    apps: "Appar",
    services: "Tjänster",
    questions: "Frågor",
    spaces: "Spaces",
    assistant_templates: "Assistentmallar",
    app_templates: "Appmallar"
  };

  function translateWarning(code: string): string {
    if (code === "target_deprecated") return m.migration_warn_target_deprecated();
    if (code.startsWith("lower_token_limit:")) return m.migration_warn_lower_token_limit({ limit: code.split(":")[1] });
    if (code.startsWith("different_family:")) { const p = code.split(":"); return m.migration_warn_different_family({ from: p[1], to: p[2] }); }
    if (code === "lacks_vision") return m.migration_warn_lacks_vision();
    if (code === "lacks_reasoning") return m.migration_warn_lacks_reasoning();
    if (code === "lacks_tool_calling") return m.migration_warn_lacks_tool_calling();
    if (code === "kwargs_reset") return m.migration_warn_kwargs_reset();
    if (code.startsWith("security_classification_insufficient:")) {
      const p = code.split(":"); return m.migration_blocked_security({ count: p[1], classification: p[2] });
    }
    return code;
  }
</script>

<div class="flex flex-col gap-4 p-4">
  {#if loading}
    <div class="flex items-center justify-center py-12 text-muted">
      <Loader2 class="h-5 w-5 animate-spin mr-2" />
      <span>{m.loading()}</span>
    </div>
  {:else if error}
    <div class="border-l-2 border-negative-default bg-negative-dimmer/50 px-4 py-3 text-sm text-negative-default">
      {error}
    </div>
  {:else if history.length === 0}
    <div class="flex items-center justify-center py-12 text-muted">
      <span>{m.migration_history_empty()}</span>
    </div>
  {:else}
    <div class="overflow-x-auto">
      <table class="w-full text-sm">
        <thead>
          <tr class="border-b border-default text-left text-muted">
            <th class="px-3 py-2 font-medium w-[1%]"></th>
            <th class="px-3 py-2 font-medium">{m.migration_history_date()}</th>
            <th class="px-3 py-2 font-medium">{m.migration_history_from()}</th>
            <th class="px-3 py-2 font-medium">{m.migration_history_to()}</th>
            <th class="px-3 py-2 font-medium text-right">{m.migration_history_count()}</th>
            <th class="px-3 py-2 font-medium">{m.migration_history_by()}</th>
            <th class="px-3 py-2 font-medium">{m.migration_history_status()}</th>
          </tr>
        </thead>
        <tbody>
          {#each history as record}
            <tr
              class="border-b border-dimmer hover:bg-hover-dimmer cursor-pointer transition-colors"
              on:click={() => toggleExpand(record.id)}
            >
              <td class="px-3 py-2">
                <ChevronDown
                  size={14}
                  class="text-muted transition-transform {expandedId === record.id ? 'rotate-0' : '-rotate-90'}"
                />
              </td>
              <td class="px-3 py-2 text-muted whitespace-nowrap">
                {formatDate(record.completed_at ?? record.started_at)}
              </td>
              <td class="px-3 py-2">{record.from_model_name}</td>
              <td class="px-3 py-2">{record.to_model_name}</td>
              <td class="px-3 py-2 text-right tabular-nums">{record.migrated_count}</td>
              <td class="px-3 py-2 text-muted">{record.initiated_by_name}</td>
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
                  <div class="bg-surface-dimmer/40 border-b border-dimmer px-8 py-4">
                    <table class="text-sm w-full max-w-lg">
                      <tbody>
                        <tr>
                          <td class="py-1.5 pr-6 text-muted whitespace-nowrap">{m.migration_history_duration()}</td>
                          <td class="py-1.5 font-mono text-xs">{formatDuration(record.duration)}</td>
                        </tr>
                        {#if record.migration_details}
                          {#each Object.entries(record.migration_details).filter(([k, v]) => k !== "total" && v > 0) as [type, count]}
                            <tr>
                              <td class="py-1.5 pr-6 text-muted whitespace-nowrap">{detailLabels[type] ?? type}</td>
                              <td class="py-1.5 tabular-nums">{count}</td>
                            </tr>
                          {/each}
                        {/if}
                      </tbody>
                    </table>

                    {#if record.warnings && record.warnings.length > 0}
                      <div class="mt-3 pt-3 border-t border-dimmer">
                        <div class="flex items-center gap-1.5 text-sm text-muted mb-1.5">
                          <AlertTriangle size={13} />
                          <span>{m.migration_history_warnings()}</span>
                        </div>
                        <ul class="space-y-1 text-sm text-warning-stronger pl-5">
                          {#each record.warnings as w}
                            <li>{translateWarning(w)}</li>
                          {/each}
                        </ul>
                      </div>
                    {/if}

                    {#if record.error_message}
                      <div class="mt-3 pt-3 border-t border-dimmer text-sm text-negative-default">
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
