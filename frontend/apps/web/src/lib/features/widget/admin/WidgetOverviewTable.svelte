<!--
  The organisation's widgets at a glance: where each one lives, whether it is
  serving visitors and how much it is used. Replaces a hard ceiling on active
  widgets with visibility.
-->
<script lang="ts">
  import type { WidgetOverview, WidgetOverviewItem } from "@eneo/eneo-js";
  import { Input } from "@eneo/ui";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import * as Table from "$lib/components/ui/table/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getLocale } from "$lib/paraglide/runtime";
  import { localizeHref } from "$lib/paraglide/runtime";

  type Props = {
    overview: WidgetOverview;
  };

  let { overview }: Props = $props();

  let onlyActive = $state(false);

  const locale = getLocale();
  const number = new Intl.NumberFormat(locale);
  const day = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" });

  const items = $derived(
    onlyActive ? overview.items.filter((item) => item.status === "active") : overview.items
  );

  function statusLabel(item: WidgetOverviewItem) {
    switch (item.status) {
      case "active":
        return m.widget_admin_status_active();
      case "paused":
        return m.widget_admin_status_paused();
      case "archived":
        return m.widget_admin_status_archived();
      default:
        return m.widget_admin_status_draft();
    }
  }

  function widgetHref(item: WidgetOverviewItem) {
    return localizeHref(`/spaces/${item.space_id}/assistants/${item.target_id}/widget`);
  }

  function budgetPercent(item: WidgetOverviewItem) {
    if (!item.daily_token_budget) return 0;
    return Math.min(100, Math.round((item.budget_used_today / item.daily_token_budget) * 100));
  }
</script>

<div class="flex flex-col gap-3">
  <p class="text-secondary text-sm">
    {m.widget_admin_overview_totals({
      widgets: number.format(overview.totals.widgets),
      active: number.format(overview.totals.active),
      questions30: number.format(overview.totals.questions_30d),
      tokens30: number.format(overview.totals.tokens_30d),
      blocked30: number.format(overview.totals.blocked_30d)
    })}
  </p>

  {#if overview.items.length === 0}
    <p class="text-secondary text-sm">{m.widget_admin_overview_empty()}</p>
  {:else}
    <div class="flex justify-end">
      <Input.Switch value={onlyActive} sideEffect={({ next }) => (onlyActive = next)}>
        {m.widget_admin_overview_only_active()}
      </Input.Switch>
    </div>
    <Table.Root>
      <caption class="sr-only">{m.widget_admin_overview_caption()}</caption>
      <Table.Header>
        <Table.Row>
          <Table.Head>{m.widget_admin_overview_widget()}</Table.Head>
          <Table.Head>{m.widget_admin_overview_placement()}</Table.Head>
          <Table.Head>{m.widget_admin_status()}</Table.Head>
          <Table.Head class="text-right">{m.widget_admin_overview_questions_7d()}</Table.Head>
          <Table.Head class="text-right">{m.widget_admin_overview_questions_30d()}</Table.Head>
          <Table.Head class="text-right">{m.widget_admin_overview_tokens_30d()}</Table.Head>
          <Table.Head class="text-right">{m.widget_admin_overview_blocked_30d()}</Table.Head>
          <Table.Head>{m.widget_admin_overview_budget_today()}</Table.Head>
          <Table.Head>{m.widget_admin_overview_last_activity()}</Table.Head>
        </Table.Row>
      </Table.Header>
      <Table.Body>
        {#each items as item (item.id)}
          <Table.Row>
            <Table.Cell>
              <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from typed route segments -->
              <a class="font-medium underline-offset-2 hover:underline" href={widgetHref(item)}
                >{item.name}</a
              >
              <!-- eslint-enable svelte/no-navigation-without-resolve -->
              <p class="text-secondary text-xs">
                {m.widget_admin_overview_origins({
                  count: number.format(item.allowed_origins.length)
                })}
              </p>
            </Table.Cell>
            <Table.Cell>
              <p>{item.space_name ?? "–"}</p>
              <p class="text-secondary text-xs">{item.assistant_name ?? "–"}</p>
            </Table.Cell>
            <Table.Cell>
              <Badge
                variant={item.status === "active"
                  ? "default"
                  : item.status === "paused"
                    ? "destructive"
                    : "outline"}>{statusLabel(item)}</Badge
              >
            </Table.Cell>
            <Table.Cell class="text-right">{number.format(item.questions_7d)}</Table.Cell>
            <Table.Cell class="text-right">{number.format(item.questions_30d)}</Table.Cell>
            <Table.Cell class="text-right"
              >{number.format(item.input_tokens_30d + item.output_tokens_30d)}</Table.Cell
            >
            <Table.Cell class="text-right">{number.format(item.blocked_30d)}</Table.Cell>
            <Table.Cell>
              {#if item.status === "active"}
                <div class="flex min-w-28 flex-col gap-1">
                  <span class="text-xs"
                    >{m.widget_admin_budget_used({
                      used: number.format(item.budget_used_today),
                      budget: number.format(item.daily_token_budget)
                    })}</span
                  >
                  <div
                    class="bg-secondary h-1.5 overflow-hidden rounded-full"
                    role="progressbar"
                    aria-label={m.widget_admin_overview_budget_today()}
                    aria-valuemin="0"
                    aria-valuemax="100"
                    aria-valuenow={budgetPercent(item)}
                    aria-valuetext={`${budgetPercent(item)} %`}
                  >
                    <div
                      class={[
                        "h-full rounded-full",
                        budgetPercent(item) >= 90 ? "bg-negative-default" : "bg-accent-default"
                      ]}
                      style:width="{budgetPercent(item)}%"
                    ></div>
                  </div>
                </div>
              {:else}
                <span class="text-secondary">–</span>
              {/if}
            </Table.Cell>
            <Table.Cell>
              {item.last_activity
                ? day.format(new Date(item.last_activity))
                : m.widget_admin_overview_never()}
            </Table.Cell>
          </Table.Row>
        {/each}
      </Table.Body>
    </Table.Root>
  {/if}
</div>
