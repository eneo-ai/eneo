<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Read-only history of model migrations (completion + transcription, merged and
  sorted by date with a type column). Each row expands to show per-entity-type
  counts, warnings, and any error message — driven by an expander button rather
  than a click-anywhere row so keyboard navigation works without custom key
  handlers.
-->

<script lang="ts">
  import { onMount } from "svelte";
  import { Loader2, ChevronDown, AlertTriangle, Search } from "lucide-svelte";

  import { getIntric } from "$lib/core/Intric";
  import { m } from "$lib/paraglide/messages";

  import * as Table from "$lib/components/ui/table/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";

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
    // Client-side tag: which model type this row came from (the two histories
    // live in separate backend endpoints and are merged here).
    model_type: "completion" | "transcription";
  };

  type StatusVariant = "default" | "secondary" | "destructive" | "outline";

  const intric = getIntric();

  let history = $state<MigrationRecord[]>([]);
  let loading = $state(true);
  let error = $state<string | null>(null);
  let lastLoadedVersion = 0;
  let expandedId = $state<string | null>(null);

  // --- Filters (client-side; add more dimensions here as needed) ----------
  let searchTerm = $state("");
  // Plain strings so they bind directly to the shadcn Select.
  let typeFilter = $state("all");
  let statusFilter = $state("all");

  const filteredHistory = $derived(
    history.filter((record) => {
      if (typeFilter !== "all" && record.model_type !== typeFilter) return false;
      if (statusFilter !== "all" && record.status !== statusFilter) return false;
      const query = searchTerm.trim().toLowerCase();
      if (query) {
        const haystack =
          `${record.from_model_name} ${record.to_model_name} ${record.initiated_by_name}`.toLowerCase();
        if (!haystack.includes(query)) return false;
      }
      return true;
    })
  );

  const hasActiveFilter = $derived(
    !!searchTerm.trim() || typeFilter !== "all" || statusFilter !== "all"
  );

  function clearFilters() {
    searchTerm = "";
    typeFilter = "all";
    statusFilter = "all";
  }

  const typeFilterLabel = $derived(
    typeFilter === "completion"
      ? m.completion_models()
      : typeFilter === "transcription"
        ? m.transcription_models()
        : m.filter_all()
  );
  const statusFilterLabel = $derived(
    statusFilter === "all" ? m.filter_all() : statusLabel(statusFilter)
  );

  async function loadHistory() {
    loading = true;
    error = null;
    try {
      const [completion, transcription] = await Promise.all([
        intric.models.getAllMigrationHistory(),
        intric.models.getAllTranscriptionMigrationHistory()
      ]);
      const tag = (
        records: unknown,
        model_type: "completion" | "transcription"
      ): MigrationRecord[] =>
        (records as Omit<MigrationRecord, "model_type">[]).map((r) => ({ ...r, model_type }));
      history = [...tag(completion, "completion"), ...tag(transcription, "transcription")].sort(
        (a, b) => {
          const da = new Date(a.completed_at ?? a.started_at ?? 0).getTime();
          const db = new Date(b.completed_at ?? b.started_at ?? 0).getTime();
          return db - da;
        }
      );
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
    <div class="mb-3 flex flex-wrap items-center gap-2">
      <div class="relative min-w-[14rem] flex-1">
        <Search
          class="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 size-4 -translate-y-1/2"
          aria-hidden="true"
        />
        <Input
          type="search"
          bind:value={searchTerm}
          placeholder={m.search()}
          class="pl-8"
          aria-label={m.search()}
        />
      </div>

      <Select.Root type="single" bind:value={typeFilter}>
        <Select.Trigger class="w-[12rem]" aria-label={m.migration_history_type()}>
          <span class="truncate">{typeFilterLabel}</span>
        </Select.Trigger>
        <Select.Content>
          <Select.Item value="all" label={m.filter_all()}>{m.filter_all()}</Select.Item>
          <Select.Item value="completion" label={m.completion_models()}>
            {m.completion_models()}
          </Select.Item>
          <Select.Item value="transcription" label={m.transcription_models()}>
            {m.transcription_models()}
          </Select.Item>
        </Select.Content>
      </Select.Root>

      <Select.Root type="single" bind:value={statusFilter}>
        <Select.Trigger class="w-[12rem]" aria-label={m.migration_history_status()}>
          <span class="truncate">{statusFilterLabel}</span>
        </Select.Trigger>
        <Select.Content>
          <Select.Item value="all" label={m.filter_all()}>{m.filter_all()}</Select.Item>
          <Select.Item value="completed" label={m.migration_status_completed()}>
            {m.migration_status_completed()}
          </Select.Item>
          <Select.Item value="failed" label={m.migration_status_failed()}>
            {m.migration_status_failed()}
          </Select.Item>
          <Select.Item value="in_progress" label={m.migration_status_in_progress()}>
            {m.migration_status_in_progress()}
          </Select.Item>
        </Select.Content>
      </Select.Root>

      {#if hasActiveFilter}
        <Button variant="ghost" size="sm" onclick={clearFilters}>{m.clear()}</Button>
      {/if}
    </div>

    {#if filteredHistory.length === 0}
      <div class="text-muted flex items-center justify-center py-12">
        <span>{m.no_results()}</span>
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
            <Table.Head>{m.migration_history_type()}</Table.Head>
            <Table.Head>{m.migration_history_status()}</Table.Head>
          </Table.Row>
        </Table.Header>

        <Table.Body>
          {#each filteredHistory as record (record.id)}
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
                <Badge variant="secondary">
                  {record.model_type === "transcription"
                    ? m.transcription_models()
                    : m.completion_models()}
                </Badge>
              </Table.Cell>
              <Table.Cell>
                <Badge variant={statusVariant(record.status)}>{statusLabel(record.status)}</Badge>
              </Table.Cell>
            </Table.Row>

            {#if isExpanded}
              <Table.Row id="migration-detail-{record.id}">
                <Table.Cell colspan={8} class="bg-muted/40 p-0">
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
  {/if}
</div>
