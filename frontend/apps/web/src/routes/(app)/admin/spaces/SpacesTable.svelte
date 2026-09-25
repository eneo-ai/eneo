<!--
  One row per shared space. Columns drop out as the page narrows and their
  content moves into a line under the name, so nothing is lost and nothing
  scrolls sideways. Only the name and "Öppna ytan" are links.
-->
<script lang="ts">
  import type { AdminSpaceListItem } from "@eneo/eneo-js";
  import { ArrowDown, ArrowUp, ArrowUpDown, Inbox, TriangleAlert, X } from "@lucide/svelte";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { intlLocale } from "$lib/core/formatting/dateTime";
  import SecurityClassificationBadge from "$lib/features/security-classifications/components/SecurityClassificationBadge.svelte";
  import SpaceChip from "$lib/features/spaces/components/SpaceChip.svelte";
  import { activityLabel } from "$lib/features/spaces/oversight/activity";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import {
    activeWidgetCount,
    adminNames,
    groupCount,
    listMembershipLabel,
    resourceSummary
  } from "./labels";
  import { isMember, type SortColumn, type SpaceListQuery } from "./space-list-query";

  type Props = {
    items: readonly AdminSpaceListItem[];
    query: SpaceListQuery;
    securityEnabled: boolean;
    /** The table's caption; it says what the list is sorted by. */
    caption: string;
    onSort: (column: SortColumn) => void;
    onClearFilters: () => void;
  };

  let { items, query, securityEnabled, caption, onSort, onClearFilters }: Props = $props();

  const number = new Intl.NumberFormat(intlLocale());
  const format = (value: number) => number.format(value);

  function columnLabel(column: SortColumn) {
    switch (column) {
      case "name":
        return m.admin_spaces_col_space();
      case "members":
        return m.members();
      case "activity":
        return m.admin_spaces_col_last_active();
      default:
        return column satisfies never;
    }
  }

  function ariaSort(column: SortColumn) {
    if (query.sort !== column) return undefined;
    return query.dir === "asc" ? "ascending" : "descending";
  }
</script>

{#snippet sortButton(column: SortColumn, align: "start" | "end" = "start")}
  {@const active = query.sort === column}
  <button
    type="button"
    class={[
      "hover:text-primary focus-visible:ring-ring/50 -mx-1.5 inline-flex min-h-8 items-center gap-1 rounded-md px-1.5 font-medium outline-none focus-visible:ring-3",
      align === "end" && "flex-row-reverse"
    ]}
    aria-label={m.admin_spaces_sort_by({ column: columnLabel(column) })}
    onclick={() => onSort(column)}
  >
    {columnLabel(column)}
    {#if !active}
      <ArrowUpDown class="text-secondary size-3.5" aria-hidden="true" />
    {:else if query.dir === "asc"}
      <ArrowUp class="size-3.5" aria-hidden="true" />
    {:else}
      <ArrowDown class="size-3.5" aria-hidden="true" />
    {/if}
  </button>
{/snippet}

{#snippet noAdmin()}
  <span class="text-warning-stronger inline-flex items-center gap-1">
    <TriangleAlert class="size-3.5 shrink-0" aria-hidden="true" />
    {m.admin_spaces_admins_missing()}
  </span>
{/snippet}

{#snippet openLink(item: AdminSpaceListItem)}
  <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from a typed id -->
  <a
    class="text-accent-stronger inline-flex min-h-6 items-center text-sm font-medium underline underline-offset-2"
    href={localizeHref(`/spaces/${item.id}/overview`)}
    aria-label={m.admin_spaces_open_space_named({ name: item.name })}
    >{m.admin_spaces_open_space()}</a
  >
  <!-- eslint-enable svelte/no-navigation-without-resolve -->
{/snippet}

<div class="border-default bg-primary overflow-hidden rounded-lg border">
  <Table.Root
    class="[&_td]:px-3 [&_td]:py-3 [&_td]:align-top [&_td]:whitespace-normal [&_th]:px-3 [&_th]:whitespace-normal @3xl:[&_td]:px-4 @3xl:[&_th]:px-4"
  >
    <Table.Caption class="sr-only">{caption}</Table.Caption>
    <Table.Header>
      <Table.Row>
        <Table.Head scope="col" aria-sort={ariaSort("name")}
          >{@render sortButton("name")}</Table.Head
        >
        {#if securityEnabled}
          <Table.Head scope="col" class="hidden @3xl:table-cell">
            {m.admin_spaces_col_classification()}
          </Table.Head>
        {/if}
        <Table.Head scope="col" class="hidden @3xl:table-cell"
          >{m.admin_spaces_col_admins()}</Table.Head
        >
        <Table.Head scope="col" class="text-right" aria-sort={ariaSort("members")}>
          {@render sortButton("members", "end")}
        </Table.Head>
        <Table.Head scope="col" class="hidden @5xl:table-cell">
          {m.admin_spaces_col_resources()}
        </Table.Head>
        <Table.Head scope="col" class="hidden @5xl:table-cell" aria-sort={ariaSort("activity")}>
          {@render sortButton("activity")}
        </Table.Head>
        <Table.Head scope="col" class="hidden @3xl:table-cell">
          {m.admin_spaces_col_membership()}
        </Table.Head>
      </Table.Row>
    </Table.Header>
    <Table.Body>
      {#each items as item (item.id)}
        {@const admins = adminNames(item.admins)}
        {@const noAdminFlag = item.attention.includes("no_admin")}
        {@const widgetWaiting = item.attention.includes("widget_activation_requested")}
        <Table.Row>
          <th scope="row" class="py-3 text-left align-top font-normal">
            <div class="flex min-w-0 items-start gap-3">
              <!-- Decoration only; on a phone the width goes to the name. -->
              <span class="hidden @md:contents">
                <SpaceChip space={{ ...item, personal: false }} />
              </span>
              <div class="flex min-w-0 flex-1 flex-col gap-1">
                <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from a typed id -->
                <a
                  class="w-fit font-medium wrap-anywhere underline-offset-2 hover:underline"
                  href={localizeHref(`/admin/spaces/${item.id}`)}>{item.name}</a
                >
                <!-- eslint-enable svelte/no-navigation-without-resolve -->
                {#if item.description}
                  <p class="text-secondary line-clamp-1 text-sm wrap-anywhere">
                    {item.description}
                  </p>
                {/if}
                {#if noAdminFlag || widgetWaiting}
                  <div class="flex flex-wrap gap-1.5">
                    {#if noAdminFlag}
                      <Badge variant="outline" class="h-auto whitespace-normal">
                        <TriangleAlert class="text-warning-stronger" aria-hidden="true" />
                        {m.admin_spaces_badge_no_admin()}
                      </Badge>
                    {/if}
                    {#if widgetWaiting}
                      <Badge variant="outline" class="h-auto whitespace-normal">
                        <Inbox aria-hidden="true" />
                        {m.admin_spaces_badge_widget_waiting()}
                      </Badge>
                    {/if}
                  </div>
                {/if}
                <!-- What the hidden columns hold, while they are hidden. -->
                <div class="text-secondary flex flex-col gap-1 text-xs wrap-anywhere @5xl:hidden">
                  {#if securityEnabled}
                    <span class="@3xl:hidden">
                      {#if item.security_classification}
                        <SecurityClassificationBadge
                          classification={item.security_classification}
                          labelled
                        />
                      {:else}
                        {m.no_classification()}
                      {/if}
                    </span>
                  {/if}
                  <span class="@3xl:hidden">
                    {#if admins}
                      {m.admin_spaces_meta_admins({ names: admins })}
                    {:else}
                      {@render noAdmin()}
                    {/if}
                  </span>
                  <span>
                    {resourceSummary(item.resources, format)}
                    · {m.admin_spaces_meta_last_active({
                      activity: activityLabel(item.last_activity)
                    })}
                  </span>
                  <span class="flex flex-wrap items-center gap-x-2 @3xl:hidden">
                    {listMembershipLabel(item.viewer_membership)}
                    {#if isMember(item)}
                      {@render openLink(item)}
                    {/if}
                  </span>
                </div>
              </div>
            </div>
          </th>
          {#if securityEnabled}
            <Table.Cell class="hidden @3xl:table-cell">
              {#if item.security_classification}
                <SecurityClassificationBadge
                  classification={item.security_classification}
                  class="@5xl:whitespace-nowrap"
                />
              {:else}
                <span class="text-secondary">{m.no_classification()}</span>
              {/if}
            </Table.Cell>
          {/if}
          <Table.Cell class="hidden wrap-anywhere @3xl:table-cell">
            {#if admins}
              {admins}
            {:else}
              {@render noAdmin()}
            {/if}
          </Table.Cell>
          <Table.Cell class="text-right">
            <span class="tabular-nums">{number.format(item.member_count)}</span>
            {#if item.group_count > 0}
              <span class="text-secondary block text-xs"
                >{groupCount(item.group_count, format)}</span
              >
            {/if}
          </Table.Cell>
          <Table.Cell class="hidden @5xl:table-cell">
            <span class="block">{resourceSummary(item.resources, format)}</span>
            {#if item.widgets.active > 0}
              <span class="text-secondary block text-xs">
                {activeWidgetCount(item.widgets.active, format)}
              </span>
            {/if}
          </Table.Cell>
          <Table.Cell class="hidden @5xl:table-cell">{activityLabel(item.last_activity)}</Table.Cell
          >
          <Table.Cell class="hidden @3xl:table-cell">
            <span class={["block", !isMember(item) && "text-secondary"]}>
              {listMembershipLabel(item.viewer_membership)}
            </span>
            {#if isMember(item)}
              {@render openLink(item)}
            {/if}
          </Table.Cell>
        </Table.Row>
      {:else}
        <Table.Row>
          <Table.Cell colspan={7} class="py-8 text-center">
            <p>{m.admin_spaces_empty_filtered()}</p>
            <Button variant="outline" class="mt-3 max-md:min-h-12" onclick={onClearFilters}>
              <X aria-hidden="true" data-icon="inline-start" />
              {m.admin_spaces_clear_filters()}
            </Button>
          </Table.Cell>
        </Table.Row>
      {/each}
    </Table.Body>
  </Table.Root>
</div>
