<!-- Copyright (c) 2026 Sundsvalls Kommun -->

<!--
  Presentational breakdown of the entities (assistants, apps, services,
  templates) using a completion model. Shared by the migration impact preview
  and the read-only usage tab — callers pass the data plus the framing strings
  (`title`, `spacesText`) so the same UI reads correctly in both places.

  A fixed-layout shadcn Table keeps columns from being pushed around by long
  names (cells truncate with a `title` tooltip), matching MigrationHistoryPanel.

  `filterable` opts into a search + type-filter toolbar (the read-only usage
  tab); the migration dialog leaves it off to stay task-focused.
-->

<script lang="ts">
  import { m } from "$lib/paraglide/messages";
  import { Bot, AppWindow, LayoutGrid, FileText, Search } from "lucide-svelte";
  import * as Table from "$lib/components/ui/table/index.js";
  import * as Select from "$lib/components/ui/select/index.js";
  import * as InputGroup from "$lib/components/ui/input-group/index.js";
  import type { UsageDetail } from "./usage";

  let {
    details,
    spacesCount = 0,
    title,
    spacesText = null,
    filterable = false
  }: {
    details: UsageDetail[];
    spacesCount?: number;
    title: string;
    spacesText?: string | null;
    filterable?: boolean;
  } = $props();

  type TypeMeta = { label: () => string; icon: typeof Bot };
  const typeMeta: Record<string, TypeMeta> = {
    assistant: { label: () => m.migration_summary_assistants(), icon: Bot },
    app: { label: () => m.migration_summary_apps(), icon: AppWindow },
    service: { label: () => m.migration_summary_services(), icon: LayoutGrid },
    assistant_template: { label: () => m.migration_summary_assistant_templates(), icon: FileText },
    app_template: { label: () => m.migration_summary_app_templates(), icon: FileText }
  };

  // Cluster rows by type so the same kinds sit together, in a stable order.
  // Unknown types fall to the end rather than disappearing.
  const typeOrder = ["assistant", "app", "service", "assistant_template", "app_template"];
  const orderIndex = (type: string) => {
    const i = typeOrder.indexOf(type);
    return i === -1 ? typeOrder.length : i;
  };
  const sortedDetails = $derived(
    [...details].sort((a, b) => orderIndex(a.entity_type) - orderIndex(b.entity_type))
  );

  function metaFor(type: string): TypeMeta {
    return typeMeta[type] ?? { label: () => type, icon: Bot };
  }

  // --- Filtering (only wired up when `filterable`) ----------------------
  let query = $state("");
  let typeFilter = $state("all");

  // Show the toolbar only when there's enough to filter — a single row
  // doesn't warrant a search box.
  const showToolbar = $derived(filterable && details.length > 1);

  // Only offer types that are actually present.
  const availableTypes = $derived(
    typeOrder.filter((t) => details.some((d) => d.entity_type === t))
  );
  const selectedTypeLabel = $derived(
    typeFilter === "all" ? m.model_usage_filter_all_types() : metaFor(typeFilter).label()
  );

  const normalizedQuery = $derived(query.trim().toLowerCase());
  const isFiltering = $derived(showToolbar && (normalizedQuery !== "" || typeFilter !== "all"));

  const filtered = $derived(
    sortedDetails.filter((d) => {
      if (typeFilter !== "all" && d.entity_type !== typeFilter) return false;
      if (!normalizedQuery) return true;
      return (
        d.entity_name.toLowerCase().includes(normalizedQuery) ||
        (d.space_name ?? "").toLowerCase().includes(normalizedQuery) ||
        (d.owner_name ?? "").toLowerCase().includes(normalizedQuery)
      );
    })
  );
</script>

<div class="border-border overflow-hidden rounded-lg border">
  <div class="border-border bg-muted/30 flex items-center justify-between gap-4 border-b px-4 py-3">
    <span class="text-sm font-medium">{title}</span>
    {#if isFiltering}
      <span class="text-muted-foreground text-xs whitespace-nowrap tabular-nums">
        {m.model_usage_shown_count({ shown: filtered.length, total: details.length })}
      </span>
    {/if}
  </div>

  {#if details.length > 0}
    {#if showToolbar}
      <div class="border-border flex flex-wrap items-center gap-2 border-b px-4 py-2.5">
        <InputGroup.Root class="max-w-xs flex-1">
          <InputGroup.Addon>
            <Search aria-hidden="true" />
          </InputGroup.Addon>
          <InputGroup.Input
            type="search"
            placeholder={m.model_usage_search_placeholder()}
            bind:value={query}
          />
        </InputGroup.Root>

        {#if availableTypes.length > 1}
          <Select.Root type="single" bind:value={typeFilter}>
            <Select.Trigger class="w-44">
              <span data-slot="select-value">{selectedTypeLabel}</span>
            </Select.Trigger>
            <Select.Content>
              <Select.Item value="all" label={m.model_usage_filter_all_types()}>
                {m.model_usage_filter_all_types()}
              </Select.Item>
              {#each availableTypes as t (t)}
                <Select.Item value={t} label={metaFor(t).label()}>{metaFor(t).label()}</Select.Item>
              {/each}
            </Select.Content>
          </Select.Root>
        {/if}
      </div>
    {/if}

    {#if filtered.length > 0}
      <Table.Root class="table-fixed">
        <Table.Header>
          <Table.Row>
            <Table.Head class="w-[34%]">{m.name()}</Table.Head>
            <Table.Head class="w-[22%]">{m.migration_impact_type()}</Table.Head>
            <Table.Head class="w-[22%]">{m.migration_impact_space()}</Table.Head>
            <Table.Head class="w-[22%]">{m.migration_impact_owner()}</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each filtered as entity (entity.entity_id)}
            {@const meta = metaFor(entity.entity_type)}
            {@const Icon = meta.icon}
            <Table.Row>
              <Table.Cell class="truncate font-medium" title={entity.entity_name}>
                {entity.entity_name}
              </Table.Cell>
              <Table.Cell class="text-muted-foreground">
                <span class="flex items-center gap-1.5">
                  <Icon size={14} class="flex-shrink-0" aria-hidden="true" />
                  <span class="truncate">{meta.label()}</span>
                </span>
              </Table.Cell>
              <Table.Cell
                class="text-muted-foreground truncate"
                title={entity.space_name ?? undefined}
              >
                {entity.space_name ?? "–"}
              </Table.Cell>
              <Table.Cell
                class="text-muted-foreground truncate"
                title={entity.owner_name ?? undefined}
              >
                {entity.owner_name ?? "–"}
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    {:else}
      <div class="text-muted-foreground px-4 py-6 text-center text-sm">
        {m.model_usage_no_matches()}
      </div>
    {/if}
  {/if}

  {#if spacesCount > 0 && spacesText}
    <div
      class="text-muted-foreground border-border flex items-center gap-2 border-t px-4 py-3 text-sm"
    >
      <LayoutGrid size={15} class="flex-shrink-0" aria-hidden="true" />
      <span>{spacesText}</span>
    </div>
  {/if}
</div>
