<!--
  The organisation's widgets at a glance, one card each: where it lives,
  whether it is serving visitors and how much it is used. Cards instead of a
  wide table so nothing needs to scroll sideways and each widget reads as a
  unit on any screen.
-->
<script lang="ts">
  import type { Eneo, WidgetOverview, WidgetOverviewItem } from "@eneo/eneo-js";
  import { invalidateAll } from "$app/navigation";
  import { ArrowRight, Clock, Pause } from "@lucide/svelte";
  import { settleDialog } from "$lib/components/settleDialog";
  import * as AlertDialog from "$lib/components/ui/alert-dialog/index.js";
  import { Badge } from "$lib/components/ui/badge/index.js";
  import { Button } from "$lib/components/ui/button/index.js";
  import * as Card from "$lib/components/ui/card/index.js";
  import { blockerLabel } from "./blockers";
  import { widgetStatusLabel } from "./status";
  import TimedText from "./TimedText.svelte";
  import { toastWidgetError } from "./errors";
  import { Switch } from "$lib/components/ui/switch/index.js";
  import { Label } from "$lib/components/ui/label/index.js";
  import { m } from "$lib/paraglide/messages";
  import { localizeHref } from "$lib/paraglide/runtime";
  import { intlLocale } from "$lib/core/formatting/dateTime";

  type Props = {
    overview: WidgetOverview;
    eneo: Eneo;
  };

  let { overview, eneo }: Props = $props();

  // Pausing a live widget is the kill switch, so it asks first. Activating
  // and resuming only happen after a review on the widget's own page.
  let toPause = $state<WidgetOverviewItem | null>(null);
  let busyId = $state<string | null>(null);
  let pausedId: string | null = null;
  const reviewLinks: Record<string, HTMLElement | null> = $state({});
  let onlyActiveSwitch = $state<HTMLElement | null>(null);

  // The Pause button goes away with the reload, so focus moves to the
  // paused widget's review link, or above the list once it is filtered out.
  const settler = settleDialog({
    close: () => (toPause = null),
    reload: invalidateAll,
    focusAfter: () => (pausedId ? reviewLinks[pausedId] : null) ?? onlyActiveSwitch
  });

  async function pause(item: WidgetOverviewItem) {
    if (busyId) return;
    busyId = item.id;
    try {
      await eneo.widgets.pause({ id: item.id });
    } catch (error) {
      toastWidgetError(error, m.widget_admin_could_not_pause());
      return;
    } finally {
      busyId = null;
    }
    pausedId = item.id;
    await settler.settle();
  }

  let onlyActive = $state(false);

  const locale = intlLocale();
  const number = new Intl.NumberFormat(locale);
  const day = new Intl.DateTimeFormat(locale, { day: "numeric", month: "short" });

  const items = $derived(
    onlyActive ? overview.items.filter((item) => item.status === "active") : overview.items
  );

  // The review works whether or not the administrator is a member of the space.
  function widgetHref(item: WidgetOverviewItem) {
    return localizeHref(`/admin/widgets/${item.id}`);
  }

  function blockedReason(item: WidgetOverviewItem): string {
    const blockers = item.activation_blockers ?? [];
    // Each label is a sentence of its own.
    return blockers.length ? blockers.map(blockerLabel).join(" ") : "";
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
      <Switch
        id="widget-overview-only-active"
        bind:ref={onlyActiveSwitch}
        bind:checked={onlyActive}
      />
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
              <Card.Title>
                <h2 class="flex flex-wrap items-center gap-2">
                  <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from typed route segments -->
                  <a class="underline-offset-2 hover:underline" href={widgetHref(item)}
                    >{item.name}</a
                  >
                  <!-- eslint-enable svelte/no-navigation-without-resolve -->
                  <Badge
                    variant={item.status === "active"
                      ? "default"
                      : item.status === "paused"
                        ? "destructive"
                        : "outline"}>{widgetStatusLabel(item.status)}</Badge
                  >
                  {#if item.activation_requested_at}
                    <Badge variant="outline">
                      <Clock aria-hidden="true" />
                      {m.widget_request_badge()}
                    </Badge>
                  {/if}
                </h2>
              </Card.Title>
              <Card.Description>
                {item.space_name ?? "–"} · {item.assistant_name ?? "–"} ·
                {item.allowed_origins.length === 1
                  ? m.widget_admin_overview_origins_one()
                  : m.widget_admin_overview_origins({
                      count: number.format(item.allowed_origins.length)
                    })}
              </Card.Description>
              <Card.Action>
                <!-- eslint-disable svelte/no-navigation-without-resolve -- localized href built from typed route segments -->
                <a
                  bind:this={reviewLinks[item.id]}
                  class="text-accent-stronger inline-flex min-h-6 items-center gap-1 text-sm underline-offset-2 hover:underline max-md:min-h-11"
                  href={widgetHref(item)}
                  aria-label={m.widget_admin_overview_review_named({ name: item.name })}
                >
                  {m.widget_admin_overview_review()}
                  <ArrowRight class="size-4" aria-hidden="true" />
                </a>
                <!-- eslint-enable svelte/no-navigation-without-resolve -->
              </Card.Action>
            </Card.Header>
            <Card.Content class="flex flex-col gap-4">
              {#if item.activation_requested_at}
                <p class="flex items-start gap-2 text-sm">
                  <Clock class="text-secondary mt-0.5 size-4 shrink-0" aria-hidden="true" />
                  <span>
                    <TimedText
                      message={(date) =>
                        item.activation_requested_by
                          ? m.widget_admin_overview_awaiting_requested_line({
                              date,
                              name: item.activation_requested_by.name
                            })
                          : m.widget_admin_overview_awaiting_requested_line_unknown({ date })}
                      value={item.activation_requested_at}
                    />
                  </span>
                </p>
              {/if}
              {#if item.status === "active" && blockedReason(item)}
                <!-- Live, but not serving as configured: say so where the badge says "Aktiv". -->
                <p class="bg-warning-dimmer text-warning-stronger rounded-lg px-3 py-2 text-sm">
                  {m.widget_admin_overview_active_issues({ reasons: blockedReason(item) })}
                </p>
              {/if}
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
                {#if item.status === "active"}
                  <div
                    role="group"
                    aria-label={m.widget_admin_overview_actions({ name: item.name })}
                  >
                    <Button
                      variant="outline"
                      size="sm"
                      class="max-md:min-h-11"
                      disabled={busyId === item.id}
                      onclick={() => (toPause = item)}
                    >
                      <Pause aria-hidden="true" data-icon="inline-start" />
                      {m.widget_admin_pause()}
                    </Button>
                  </div>
                {:else if item.status !== "archived" && blockedReason(item)}
                  <p class="text-warning-stronger text-xs">
                    {m.widget_admin_overview_blocked({ reasons: blockedReason(item) })}
                  </p>
                {/if}
              </div>
            </Card.Content>
          </Card.Root>
        </li>
      {/each}
    </ul>
  {/if}
</div>

<AlertDialog.Root
  bind:open={
    () => toPause !== null,
    (open) => {
      if (!open && busyId === null) toPause = null;
    }
  }
>
  <AlertDialog.Content
    onOpenAutoFocus={() => settler.reset()}
    onCloseAutoFocus={settler.onCloseAutoFocus}
  >
    <AlertDialog.Header>
      <AlertDialog.Title>
        {m.widget_admin_overview_pause_title({ name: toPause?.name ?? "" })}
      </AlertDialog.Title>
      <AlertDialog.Description
        >{m.widget_admin_overview_pause_description()}</AlertDialog.Description
      >
    </AlertDialog.Header>
    <AlertDialog.Footer>
      <!-- bits' Cancel ignores `disabled`; the open setter above refuses to close while pausing. -->
      <AlertDialog.Cancel
        aria-disabled={busyId !== null}
        class={busyId !== null ? "pointer-events-none opacity-50" : undefined}
        >{m.cancel()}</AlertDialog.Cancel
      >
      <!-- aria-disabled, not disabled, while pausing: a focused button that becomes disabled drops focus. -->
      <AlertDialog.Action
        aria-disabled={busyId !== null}
        aria-busy={busyId !== null}
        class={busyId !== null ? "pointer-events-none opacity-50" : undefined}
        onclick={(event) => {
          event.preventDefault();
          if (toPause) void pause(toPause);
        }}
        >{busyId !== null ? m.widget_review_pausing() : m.widget_admin_pause()}</AlertDialog.Action
      >
    </AlertDialog.Footer>
  </AlertDialog.Content>
</AlertDialog.Root>
