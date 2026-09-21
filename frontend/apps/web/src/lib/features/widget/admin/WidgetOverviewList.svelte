<!--
  The organisation's widgets at a glance, one card each: where it lives,
  whether it is serving visitors and how much it is used. Cards instead of a
  wide table so nothing needs to scroll sideways and each widget reads as a
  unit on any screen.
-->
<script lang="ts">
  import type { Eneo, WidgetOverview, WidgetOverviewItem } from "@eneo/eneo-js";
  import { invalidateAll } from "$app/navigation";
  import { ArrowRight, Pause, Play } from "lucide-svelte";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import { blockerLabel } from "./blockers";
  import { toastWidgetError } from "./errors";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { m } from "$lib/paraglide/messages";
  import { getLocale, localizeHref } from "$lib/paraglide/runtime";

  type Props = {
    overview: WidgetOverview;
    eneo: Eneo;
  };

  let { overview, eneo }: Props = $props();

  // Pausing a live widget is the kill switch, so it asks first; resuming and
  // activating are safe to do straight away. The list is reloaded afterwards.
  let toPause = $state<WidgetOverviewItem | null>(null);
  let busyId = $state<string | null>(null);

  async function run(item: WidgetOverviewItem, action: "pause" | "activate") {
    busyId = item.id;
    try {
      if (action === "pause") await eneo.widgets.pause({ id: item.id });
      else await eneo.widgets.activate({ id: item.id });
      toPause = null;
      await invalidateAll();
    } catch (error) {
      toastWidgetError(
        error,
        action === "pause" ? m.widget_admin_could_not_pause() : m.widget_admin_could_not_activate()
      );
    } finally {
      busyId = null;
    }
  }

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

  function blockedReason(item: WidgetOverviewItem): string {
    const blockers = item.activation_blockers ?? [];
    return blockers.length ? blockers.map(blockerLabel).join(", ") : "";
  }

  function budgetPercent(item: WidgetOverviewItem) {
    if (!item.daily_token_budget) return 0;
    return Math.min(100, Math.round((item.budget_used_today / item.daily_token_budget) * 100));
  }
</script>

<div class="flex flex-col gap-4">
  {#if overview.items.length > 0}
    <div class="flex items-center justify-end gap-2">
      <Label for="widget-overview-only-active">{m.widget_admin_overview_only_active()}</Label>
      <Switch id="widget-overview-only-active" bind:checked={onlyActive} />
    </div>
  {/if}

  {#if overview.items.length === 0}
    <p class="text-secondary text-sm">{m.widget_admin_overview_empty()}</p>
  {:else}
    <ul class="grid gap-4 xl:grid-cols-2" aria-label={m.widget_admin_overview_caption()}>
      {#each items as item (item.id)}
        <li>
          <Card.Root class="h-full">
            <Card.Header class="border-b">
              <Card.Title class="flex flex-wrap items-center gap-2">
                <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from typed route segments -->
                <a class="underline-offset-2 hover:underline" href={widgetHref(item)}>{item.name}</a
                >
                <!-- eslint-enable svelte/no-navigation-without-resolve -->
                <Badge
                  variant={item.status === "active"
                    ? "default"
                    : item.status === "paused"
                      ? "destructive"
                      : "outline"}>{statusLabel(item)}</Badge
                >
              </Card.Title>
              <Card.Description>
                {item.space_name ?? "–"} · {item.assistant_name ?? "–"} ·
                {m.widget_admin_overview_origins({
                  count: number.format(item.allowed_origins.length)
                })}
              </Card.Description>
              <Card.Action>
                <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from typed route segments -->
                <a
                  class="text-accent-default inline-flex items-center gap-1 text-sm underline-offset-2 hover:underline"
                  href={widgetHref(item)}
                  aria-label={m.widget_admin_overview_open({ name: item.name })}
                >
                  {m.widget_admin_open()}
                  <ArrowRight class="size-4" aria-hidden="true" />
                </a>
                <!-- eslint-enable svelte/no-navigation-without-resolve -->
              </Card.Action>
            </Card.Header>
            <Card.Content class="flex flex-col gap-4">
              <dl class="grid grid-cols-2 gap-x-4 gap-y-3 sm:grid-cols-5">
                <div>
                  <dt class="text-secondary text-xs">{m.widget_admin_overview_questions_7d()}</dt>
                  <dd class="text-lg font-semibold tabular-nums">
                    {number.format(item.questions_7d)}
                  </dd>
                </div>
                <div>
                  <dt class="text-secondary text-xs">{m.widget_admin_overview_questions_30d()}</dt>
                  <dd class="text-lg font-semibold tabular-nums">
                    {number.format(item.questions_30d)}
                  </dd>
                </div>
                <div>
                  <dt class="text-secondary text-xs">{m.widget_admin_overview_tokens_30d()}</dt>
                  <dd class="text-lg font-semibold tabular-nums">
                    {number.format(item.input_tokens_30d + item.output_tokens_30d)}
                  </dd>
                </div>
                <div>
                  <dt class="text-secondary text-xs">{m.widget_admin_overview_blocked_30d()}</dt>
                  <dd
                    class={[
                      "text-lg font-semibold tabular-nums",
                      item.blocked_30d > 0 && "text-warning-stronger"
                    ]}
                  >
                    {number.format(item.blocked_30d)}
                  </dd>
                </div>
                <div>
                  <dt class="text-secondary text-xs">{m.widget_admin_overview_feedback_30d()}</dt>
                  <dd class="text-lg font-semibold tabular-nums">
                    {m.widget_admin_overview_feedback_value({
                      helpful: number.format(item.helpful_30d),
                      unhelpful: number.format(item.unhelpful_30d)
                    })}
                  </dd>
                </div>
              </dl>

              <div class="flex flex-col gap-1">
                <div class="flex items-baseline justify-between text-xs">
                  <span class="text-secondary">{m.widget_admin_overview_budget_today()}</span>
                  <span>
                    {#if item.status === "active"}
                      {m.widget_admin_budget_used({
                        used: number.format(item.budget_used_today),
                        budget: number.format(item.daily_token_budget)
                      })}
                    {:else}
                      {m.widget_admin_overview_budget_inactive({
                        budget: number.format(item.daily_token_budget)
                      })}
                    {/if}
                  </span>
                </div>
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

              <div class="flex flex-wrap items-center justify-between gap-2">
                <p class="text-secondary text-xs">
                  {m.widget_admin_overview_last_activity()}:
                  {item.last_activity
                    ? day.format(new Date(item.last_activity))
                    : m.widget_admin_overview_never()}
                </p>
                {#if item.status !== "archived"}
                  <div
                    role="group"
                    aria-label={m.widget_admin_overview_actions({ name: item.name })}
                  >
                    {#if item.status === "active"}
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busyId === item.id}
                        onclick={() => (toPause = item)}
                      >
                        <Pause aria-hidden="true" data-icon="inline-start" />
                        {m.widget_admin_pause()}
                      </Button>
                    {:else}
                      {@const reason = blockedReason(item)}
                      <Button
                        variant="outline"
                        size="sm"
                        disabled={busyId === item.id || reason !== ""}
                        aria-describedby={reason ? `widget-overview-blocked-${item.id}` : undefined}
                        onclick={() => run(item, "activate")}
                      >
                        <Play aria-hidden="true" data-icon="inline-start" />
                        {item.status === "paused"
                          ? m.widget_admin_resume()
                          : m.widget_admin_activate()}
                      </Button>
                      {#if reason}
                        <p
                          id={`widget-overview-blocked-${item.id}`}
                          class="text-warning-stronger mt-1 text-xs"
                        >
                          {m.widget_admin_overview_blocked({ reasons: reason })}
                        </p>
                      {/if}
                    {/if}
                  </div>
                {/if}
              </div>
            </Card.Content>
          </Card.Root>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<AlertDialog.Root open={toPause !== null} onOpenChange={(open) => !open && (toPause = null)}>
  <AlertDialog.Content>
    <AlertDialog.Header>
      <AlertDialog.Title>
        {m.widget_admin_overview_pause_title({ name: toPause?.name ?? "" })}
      </AlertDialog.Title>
      <AlertDialog.Description
        >{m.widget_admin_overview_pause_description()}</AlertDialog.Description
      >
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <AlertDialog.Cancel disabled={busyId !== null}>{m.cancel()}</AlertDialog.Cancel>
      <AlertDialog.Action
        disabled={busyId !== null}
        onclick={(event) => {
          event.preventDefault();
          if (toPause) void run(toPause, "pause");
        }}>{m.widget_admin_pause()}</AlertDialog.Action
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
