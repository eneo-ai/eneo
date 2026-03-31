<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<script lang="ts">
  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";
  import { onMount } from "svelte";
  import { Label } from "@intric/ui";
  import { Loader2 } from "lucide-svelte";

  const intric = getIntric();

  type MigrationRecord = {
    id: string;
    from_model_id: string;
    from_model_name: string;
    to_model_id: string;
    to_model_name: string;
    migrated_count: number;
    status: string;
    initiated_by_id: string;
    initiated_by_name: string;
    started_at: string | null;
    completed_at: string | null;
    duration: number | null;
    error_message: string | null;
  };

  let history: MigrationRecord[] = [];
  let loading = true;
  let error: string | null = null;

  onMount(async () => {
    try {
      const result = await intric.models.getAllMigrationHistory();
      history = result as MigrationRecord[];
    } catch (e: any) {
      error = e.message || "Failed to load migration history";
    } finally {
      loading = false;
    }
  });

  function formatDate(dateStr: string | null): string {
    if (!dateStr) return "-";
    const date = new Date(dateStr);
    return date.toLocaleDateString(undefined, {
      year: "numeric",
      month: "short",
      day: "numeric",
      hour: "2-digit",
      minute: "2-digit"
    });
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
            <tr class="border-b border-dimmer hover:bg-hover-dimmer">
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
          {/each}
        </tbody>
      </table>
    </div>
  {/if}
</div>
