<script lang="ts">
  import type { FlowSparse } from "@eneo/eneo-js";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getAppContext } from "$lib/core/AppContext";
  import * as Table from "$lib/components/ui/table/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import FlowActions from "./FlowActions.svelte";
  import { m } from "$lib/paraglide/messages";
  import { getLocale, localizeHref } from "$lib/paraglide/runtime";
  import {
    buildFlowListRows,
    describeUpdatedAt,
    filterFlowListRows,
    type FlowListFilter,
    type FlowListRow
  } from "./flowListRows";

  interface Props {
    flows: FlowSparse[];
    canCreate?: boolean;
    oncreate?: () => void;
  }

  let { flows, canCreate = false, oncreate }: Props = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();
  const { user } = getAppContext();

  let query = $state("");
  let filter = $state<FlowListFilter>("all");

  const rows = $derived(buildFlowListRows(flows));
  const visibleRows = $derived(filterFlowListRows(rows, { query, filter }));
  const isEmpty = $derived(rows.length === 0);
  const noMatch = $derived(!isEmpty && visibleRows.length === 0);
  const now = new Date();
  const locale = getLocale();

  const filters: { value: FlowListFilter; label: () => string }[] = [
    { value: "all", label: m.flow_list_filter_all },
    { value: "published", label: m.flow_list_filter_published },
    { value: "drafts", label: m.flow_list_filter_drafts }
  ];

  const memberNames = $derived(
    new Map($currentSpace.members.map((member) => [member.id, member.username || member.email]))
  );

  function ownerLabel(row: FlowListRow): string {
    if (row.ownerUserId === user.id) return m.flow_list_owner_you();
    if (!row.ownerUserId) return "—";
    return memberNames.get(row.ownerUserId) ?? m.flow_list_owner_unknown();
  }

  function updatedLabel(row: FlowListRow): string {
    const described = describeUpdatedAt(row.updatedAt, now, locale);
    switch (described.kind) {
      case "today":
        return m.flow_list_updated_today({ time: described.time });
      case "yesterday":
        return m.flow_list_updated_yesterday({ time: described.time });
      case "days_ago":
        return m.flow_list_updated_days_ago({ days: String(described.days) });
      case "date":
        return described.date;
      case "unknown":
        return "—";
    }
  }

  function updatedTitle(row: FlowListRow): string {
    if (!row.updatedAt) return "";
    const date = new Date(row.updatedAt);
    return Number.isNaN(date.getTime()) ? "" : date.toLocaleString(locale);
  }

  function statusLabel(row: FlowListRow): string {
    return row.status === "published" ? m.flow_list_status_published() : m.flow_list_status_draft();
  }

  function statusClass(row: FlowListRow): string {
    return row.status === "published"
      ? "bg-positive-dimmer text-positive-stronger"
      : "bg-accent-dimmer text-accent-stronger";
  }

  function rowHref(row: FlowListRow): string {
    return localizeHref(`/spaces/${$currentSpace.routeId}/flows/${row.id}`);
  }

  function rowName(row: FlowListRow): string {
    return row.name;
  }
</script>

<!-- Rendered in the actions column on a wide list and under the name once that
     column is dropped, so a narrow row keeps every action it had. -->
{#snippet rowActions(row: FlowListRow)}
  <div class="flex items-center gap-1.5">
    <FlowActions flow={row.flow} />
  </div>
{/snippet}

<div class="@container/list flex flex-col gap-3">
  {#if !isEmpty}
    <div class="flex flex-wrap items-center gap-2">
      <Input
        type="search"
        bind:value={query}
        aria-label={m.flow_list_search_aria()}
        placeholder={m.flow_list_search_placeholder()}
        class="bg-primary h-[2.125rem] w-full max-w-[15rem] text-sm max-sm:h-[44px]"
      />
      <div
        class="flex flex-wrap items-center gap-1.5"
        role="group"
        aria-label={m.flow_list_filter_aria()}
      >
        {#each filters as option (option.value)}
          <Button
            variant="outline"
            size="sm"
            class="rounded-full font-medium max-sm:h-[44px] max-sm:px-4 {filter === option.value
              ? 'border-stronger bg-tertiary text-primary'
              : 'text-secondary'}"
            aria-pressed={filter === option.value}
            onclick={() => (filter = option.value)}
          >
            {option.label()}
          </Button>
        {/each}
      </div>
      <p class="text-secondary ml-auto text-xs max-sm:ml-0 max-sm:w-full">
        {visibleRows.length === 1
          ? m.flow_list_count_one()
          : m.flow_list_count({ count: String(visibleRows.length) })}
      </p>
    </div>
  {/if}

  <div class="border-default bg-primary overflow-hidden rounded-xl border">
    {#if isEmpty}
      <div class="flex flex-col items-center px-6 py-11 text-center">
        <p class="text-primary text-[0.9375rem] font-semibold">{m.flow_list_empty_title()}</p>
        <p class="text-secondary mt-1.5 max-w-[46ch] text-sm leading-relaxed text-pretty">
          {m.flow_list_empty_description()}
        </p>
        {#if canCreate}
          <Button class="mt-4" onclick={() => oncreate?.()}>{m.flow_create_button()}</Button>
        {/if}
      </div>
    {:else}
      <Table.Root class="table-fixed border-separate border-spacing-0">
        <Table.Header>
          <Table.Row class="hover:bg-transparent">
            <Table.Head
              class="text-secondary border-default h-10 border-b px-4 text-xs font-semibold"
            >
              {m.name()}
            </Table.Head>
            <Table.Head
              class="text-secondary border-default hidden h-10 w-[16rem] border-b px-4 text-xs font-semibold @[52rem]/list:table-cell"
            >
              {m.status()}
            </Table.Head>
            <Table.Head
              class="text-secondary border-default hidden h-10 w-[8rem] border-b px-4 text-xs font-semibold @[52rem]/list:table-cell"
            >
              {m.flow_list_owner()}
            </Table.Head>
            <Table.Head
              class="text-secondary border-default hidden h-10 w-[9.5rem] border-b px-4 text-xs font-semibold @[52rem]/list:table-cell"
              aria-sort="descending"
            >
              <span class="inline-flex items-center gap-1">
                {m.flow_list_updated()}
                <span aria-hidden="true" class="text-[0.5625rem]">▼</span>
              </span>
            </Table.Head>
            <Table.Head
              class="border-default hidden h-10 w-[7.5rem] border-b px-4 text-right @[52rem]/list:table-cell"
            >
              <span class="sr-only">{m.actions()}</span>
            </Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#if noMatch}
            <Table.Row class="hover:bg-transparent">
              <Table.Cell colspan={5} class="px-6 py-9 text-center whitespace-normal">
                {#if query.trim()}
                  <p class="text-primary text-sm font-semibold">{m.flow_list_no_match_title()}</p>
                  <Button variant="link" class="mt-1 h-auto p-0" onclick={() => (query = "")}>
                    {m.flow_list_clear_search()}
                  </Button>
                {:else}
                  <p class="text-primary text-sm font-semibold">
                    {filter === "published"
                      ? m.flow_list_no_published_title()
                      : m.flow_list_no_drafts_title()}
                  </p>
                  <Button variant="link" class="mt-1 h-auto p-0" onclick={() => (filter = "all")}>
                    {m.flow_list_show_all()}
                  </Button>
                {/if}
              </Table.Cell>
            </Table.Row>
          {/if}
          {#each visibleRows as row (row.kind + row.id)}
            <Table.Row class="border-dimmer hover:bg-secondary/40 group transition-colors">
              <Table.Cell class="border-dimmer border-b px-4 py-3 align-middle whitespace-normal">
                <div class="flex min-w-0 flex-col gap-0.5">
                  <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing for dynamic paths -->
                  <a
                    href={rowHref(row)}
                    class="text-primary focus-visible:ring-ring/40 truncate rounded-sm text-[0.875rem] font-semibold outline-none focus-visible:ring-2"
                  >
                    {rowName(row)}
                  </a>
                  <!-- eslint-enable svelte/no-navigation-without-resolve -->
                  {#if row.subtitle}
                    <span class="text-secondary truncate text-xs" title={row.subtitle}>
                      {row.subtitle}
                    </span>
                  {/if}
                  <span class="mt-0.5 flex flex-wrap items-center gap-2 @[52rem]/list:hidden">
                    <Badge
                      class="max-w-full border-transparent {statusClass(row)}"
                      title={statusLabel(row)}
                    >
                      <span class="truncate">{statusLabel(row)}</span>
                    </Badge>
                    <span class="text-secondary text-xs" title={updatedTitle(row)}>
                      {updatedLabel(row)}
                    </span>
                  </span>
                  <div class="mt-2 flex @[52rem]/list:hidden">{@render rowActions(row)}</div>
                </div>
              </Table.Cell>
              <Table.Cell
                class="border-dimmer hidden border-b px-4 py-3 align-middle @[52rem]/list:table-cell"
              >
                <Badge
                  class="max-w-full border-transparent {statusClass(row)}"
                  title={statusLabel(row)}
                >
                  <span class="truncate">{statusLabel(row)}</span>
                </Badge>
              </Table.Cell>
              <Table.Cell
                class="text-secondary border-dimmer hidden border-b px-4 py-3 align-middle text-sm @[52rem]/list:table-cell"
              >
                {ownerLabel(row)}
              </Table.Cell>
              <Table.Cell
                class="text-secondary border-dimmer hidden border-b px-4 py-3 align-middle text-sm tabular-nums @[52rem]/list:table-cell"
                title={updatedTitle(row)}
              >
                {updatedLabel(row)}
              </Table.Cell>
              <Table.Cell
                class="border-dimmer hidden border-b px-3 py-2 text-right align-middle @[52rem]/list:table-cell"
              >
                <div class="flex justify-end">{@render rowActions(row)}</div>
              </Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
    {/if}
  </div>
</div>
