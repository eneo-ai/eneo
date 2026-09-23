<script lang="ts">
  import type { FlowSparse } from "@eneo/eneo-js";
  import type { RecoverableAIBuilderDraftSession } from "$lib/features/flows/ai-builder/protocol";
  import { getSpacesManager } from "$lib/features/spaces/SpacesManager";
  import { getAppContext } from "$lib/core/AppContext";
  import { resolve } from "$app/paths";
  import * as Table from "$lib/components/ui/table/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import { Input } from "$lib/components/ui/input/index.js";
  import * as DropdownMenu from "$lib/components/ui/dropdown-menu/index.js";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import * as Empty from "$lib/components/ui/empty/index.js";
  import * as ToggleGroup from "$lib/components/ui/toggle-group/index.js";
  import { IconEllipsis } from "@eneo/icons/ellipsis";
  import ChevronDown from "@lucide/svelte/icons/chevron-down";
  import Search from "@lucide/svelte/icons/search";
  import { IconTrash } from "@eneo/icons/trash";
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
    drafts: RecoverableAIBuilderDraftSession[];
    /** The drafts request failed; the list must say so instead of hiding rows. */
    draftsUnavailable?: boolean;
    canCreate?: boolean;
    oncreate?: () => void;
    ondiscarddraft?: (sessionId: string) => Promise<void> | void;
  }

  let {
    flows,
    drafts,
    draftsUnavailable = false,
    canCreate = false,
    oncreate,
    ondiscarddraft
  }: Props = $props();

  const {
    state: { currentSpace }
  } = getSpacesManager();
  const { user } = getAppContext();

  let query = $state("");
  let filter = $state<FlowListFilter>("all");
  let draftPendingDiscard = $state<FlowListRow | null>(null);
  let isDiscarding = $state(false);

  const rows = $derived(buildFlowListRows(flows, drafts));
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
    if (row.kind === "ai_draft" || row.ownerUserId === user.id) return m.flow_list_owner_you();
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

  // Status is a word on a quiet chip: moss for published, neutral for a draft,
  // so civic blue stays on the things you can press.
  function statusClass(row: FlowListRow): string {
    return row.status === "published"
      ? "bg-positive-dimmer text-positive-stronger"
      : "bg-secondary text-primary";
  }

  /** An AI draft has no steps to summarise yet; its line says where it stands. */
  function rowSubtitle(row: FlowListRow): string | null {
    if (row.kind === "flow") return row.subtitle;
    return row.phase === "reviewing"
      ? m.flow_list_status_draft_reviewing()
      : m.flow_list_status_draft_understanding();
  }

  function rowHref(row: FlowListRow): string {
    if (row.kind === "flow") {
      return localizeHref(`/spaces/${$currentSpace.routeId}/flows/${row.id}`);
    }
    return localizeHref(`/spaces/${$currentSpace.routeId}/flows/ai-builder?session=${row.id}`);
  }

  function rowName(row: FlowListRow): string {
    return row.name ?? m.ai_builder_draft_untitled();
  }

  async function confirmDiscard() {
    if (!draftPendingDiscard || draftPendingDiscard.kind !== "ai_draft") return;
    isDiscarding = true;
    try {
      await ondiscarddraft?.(draftPendingDiscard.id);
      draftPendingDiscard = null;
    } finally {
      isDiscarding = false;
    }
  }
</script>

<!-- Rendered in the actions column on a wide list and under the name once that
     column is dropped, so a narrow row keeps every action it had. The owner
     column is the first to go (below 52rem); the rest stay down to 40rem. -->
{#snippet rowActions(row: FlowListRow)}
  <!-- Above the row-wide link, so the actions stay their own targets. -->
  <div class="relative z-10 flex items-center gap-1.5">
    {#if row.kind === "ai_draft"}
      <Button
        variant="outline"
        size="sm"
        class="max-sm:h-[44px] max-sm:px-4"
        href={resolve(`/spaces/${$currentSpace.routeId}/flows/ai-builder?session=${row.id}`)}
      >
        {m.flow_list_resume_draft()}
      </Button>
      <DropdownMenu.Root>
        <DropdownMenu.Trigger>
          {#snippet child({ props })}
            <Button
              {...props}
              size="icon-sm"
              variant="ghost"
              class="text-secondary hover:text-primary max-sm:size-[44px]"
              aria-label={m.actions()}
            >
              <IconEllipsis />
            </Button>
          {/snippet}
        </DropdownMenu.Trigger>
        <DropdownMenu.Content align="end" class="min-w-[10rem]">
          <DropdownMenu.Item variant="destructive" onclick={() => (draftPendingDiscard = row)}>
            <IconTrash class="size-4" />
            {m.ai_builder_discard_draft()}
          </DropdownMenu.Item>
        </DropdownMenu.Content>
      </DropdownMenu.Root>
    {:else}
      <FlowActions flow={row.flow} />
    {/if}
  </div>
{/snippet}

<div class="@container/list flex flex-col gap-3">
  {#if !isEmpty}
    <div class="flex flex-wrap items-center gap-2">
      <div class="relative w-full max-w-[16rem]">
        <Search
          class="text-secondary pointer-events-none absolute top-1/2 left-3 size-4 -translate-y-1/2"
          aria-hidden="true"
        />
        <Input
          type="search"
          bind:value={query}
          aria-label={m.flow_list_search_aria()}
          placeholder={m.flow_list_search_placeholder()}
          class="bg-primary h-[2.125rem] w-full pl-9 text-sm max-sm:h-[44px]"
        />
      </div>
      <!-- One choice of three. Clicking the chosen option again keeps it
           rather than leaving no filter selected. spacing={1}: the joined
           (spacing 0) look keys off a data-horizontal attribute bits-ui never
           sets, so joined items render square. -->
      <ToggleGroup.Root
        type="single"
        variant="outline"
        spacing={0}
        bind:value={
          () => filter,
          (value) => {
            // Clicking the chosen option again would clear it; the filter always has one.
            if (value) filter = value as FlowListFilter;
          }
        }
        aria-label={m.flow_list_filter_aria()}
      >
        {#each filters as option (option.value)}
          <ToggleGroup.Item value={option.value} class="px-3">
            {option.label()}
          </ToggleGroup.Item>
        {/each}
      </ToggleGroup.Root>
      <p class="text-secondary ml-auto text-xs max-sm:ml-0 max-sm:w-full">
        {visibleRows.length === 1
          ? m.flow_list_count_one()
          : m.flow_list_count({ count: String(visibleRows.length) })}
      </p>
    </div>
  {/if}

  {#if draftsUnavailable}
    <p class="text-secondary text-xs" role="status">{m.flow_list_drafts_unavailable()}</p>
  {/if}

  <div class="border-default bg-primary overflow-hidden rounded-xl border">
    {#if isEmpty}
      <Empty.Root class="py-11">
        <Empty.Header>
          <Empty.Title>{m.flow_list_empty_title()}</Empty.Title>
          <Empty.Description class="max-w-[46ch]">
            {m.flow_list_empty_description()}
          </Empty.Description>
        </Empty.Header>
        {#if canCreate}
          <Empty.Content>
            <Button onclick={() => oncreate?.()}>{m.flow_create_button()}</Button>
          </Empty.Content>
        {/if}
      </Empty.Root>
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
              class="text-secondary border-default hidden h-10 w-[9rem] border-b px-4 text-xs font-semibold @[40rem]/list:table-cell"
            >
              {m.status()}
            </Table.Head>
            <Table.Head
              class="text-secondary border-default hidden h-10 w-[10rem] border-b px-4 text-xs font-semibold @[52rem]/list:table-cell"
            >
              {m.flow_list_owner()}
            </Table.Head>
            <Table.Head
              class="text-secondary border-default hidden h-10 w-[9.5rem] border-b px-4 text-xs font-semibold @[40rem]/list:table-cell"
              aria-sort="descending"
            >
              <span class="inline-flex items-center gap-1">
                {m.flow_list_updated()}
                <ChevronDown class="size-3 shrink-0" aria-hidden="true" />
              </span>
            </Table.Head>
            <Table.Head
              class="border-default hidden h-10 w-[7.5rem] border-b px-4 text-right @[40rem]/list:table-cell"
            >
              <span class="sr-only">{m.actions()}</span>
            </Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#if noMatch}
            <Table.Row class="hover:bg-transparent">
              <Table.Cell colspan={5} class="whitespace-normal">
                <Empty.Root class="gap-2 py-7">
                  <Empty.Header>
                    <Empty.Title>
                      {query.trim()
                        ? m.flow_list_no_match_title()
                        : filter === "published"
                          ? m.flow_list_no_published_title()
                          : m.flow_list_no_drafts_title()}
                    </Empty.Title>
                  </Empty.Header>
                  <Empty.Content>
                    {#if query.trim()}
                      <Button variant="link" onclick={() => (query = "")}>
                        {m.flow_list_clear_search()}
                      </Button>
                    {:else}
                      <Button variant="link" onclick={() => (filter = "all")}>
                        {m.flow_list_show_all()}
                      </Button>
                    {/if}
                  </Empty.Content>
                </Empty.Root>
              </Table.Cell>
            </Table.Row>
          {/if}
          {#each visibleRows as row (row.kind + row.id)}
            <!-- The name link stretches over the row, so the whole row opens the flow. -->
            <Table.Row class="border-dimmer hover:bg-secondary/40 relative transition-colors">
              <Table.Cell class="border-dimmer border-b px-4 py-3 align-middle whitespace-normal">
                <div class="flex min-w-0 flex-col gap-0.5">
                  <!-- eslint-disable svelte/no-navigation-without-resolve -- localizeHref handles routing for dynamic paths -->
                  <a
                    href={rowHref(row)}
                    title={rowName(row)}
                    class="text-primary focus-visible:ring-ring truncate rounded-sm text-sm font-semibold outline-none before:absolute before:inset-0 before:content-[''] focus-visible:ring-2"
                  >
                    {rowName(row)}
                  </a>
                  <!-- eslint-enable svelte/no-navigation-without-resolve -->
                  {#if rowSubtitle(row)}
                    <span class="text-secondary truncate text-xs" title={rowSubtitle(row)}>
                      {rowSubtitle(row)}
                    </span>
                  {/if}
                  <span class="mt-0.5 flex flex-wrap items-center gap-2 @[40rem]/list:hidden">
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
                  <div class="mt-2 flex @[40rem]/list:hidden">{@render rowActions(row)}</div>
                </div>
              </Table.Cell>
              <Table.Cell
                class="border-dimmer hidden border-b px-4 py-3 align-middle @[40rem]/list:table-cell"
              >
                <Badge
                  class="max-w-full border-transparent {statusClass(row)}"
                  title={statusLabel(row)}
                >
                  <span class="truncate">{statusLabel(row)}</span>
                </Badge>
              </Table.Cell>
              <Table.Cell
                class="text-secondary border-dimmer hidden truncate border-b px-4 py-3 align-middle text-sm @[52rem]/list:table-cell"
                title={ownerLabel(row)}
              >
                {ownerLabel(row)}
              </Table.Cell>
              <Table.Cell
                class="text-secondary border-dimmer hidden border-b px-4 py-3 align-middle text-sm tabular-nums @[40rem]/list:table-cell"
                title={updatedTitle(row)}
              >
                {updatedLabel(row)}
              </Table.Cell>
              <Table.Cell
                class="border-dimmer hidden border-b px-3 py-2 text-right align-middle @[40rem]/list:table-cell"
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

<AlertDialog.Root
  open={draftPendingDiscard !== null}
  onOpenChange={(open) => {
    if (!open) draftPendingDiscard = null;
  }}
>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>{m.ai_builder_draft_discard_title()}</AlertDialog.Title>
      <AlertDialog.Description>{m.ai_builder_draft_discard_body()}</AlertDialog.Description>
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action variant="destructive" disabled={isDiscarding} onclick={confirmDiscard}>
        {m.ai_builder_draft_discard_action()}
      </AlertDialog.Action>
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
