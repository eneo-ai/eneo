<!-- Daily usage of a widget and how much of today's token budget is spent. -->
<script lang="ts">
  import type { Eneo, Widget, WidgetUsage } from "@eneo/eneo-js";
  import { untrack } from "svelte";
  import * as Table from "$lib/components/ui/table/index.js";
  import { m } from "$lib/paraglide/messages";
  import { intlLocale } from "$lib/core/formatting/dateTime";

  type Props = {
    widget: Widget;
    eneo: Eneo;
    /** Whether the card is on screen; it is fetched afresh each time it comes into view. */
    visible?: boolean;
  };

  let { widget, eneo, visible = true }: Props = $props();

  let usage = $state<WidgetUsage | null>(null);
  let failed = $state(false);

  const locale = intlLocale();
  const number = new Intl.NumberFormat(locale);
  const day = new Intl.DateTimeFormat(locale, { weekday: "short", day: "numeric", month: "short" });

  const budgetPercent = $derived(
    usage && usage.daily_token_budget > 0
      ? Math.min(100, Math.round((usage.budget_used_today / usage.daily_token_budget) * 100))
      : 0
  );
  const days = $derived(usage ? [...usage.days].reverse() : []);
  const totals = $derived(
    days.reduce(
      (sum, row) => ({
        questions: sum.questions + row.questions,
        blocked: sum.blocked + row.blocked_budget + row.blocked_rate,
        helpful: sum.helpful + row.helpful,
        unhelpful: sum.unhelpful + row.unhelpful
      }),
      { questions: 0, blocked: 0, helpful: 0, unhelpful: 0 }
    )
  );

  let requests = 0;
  async function load() {
    const request = ++requests;
    try {
      const answer = await eneo.widgets.usage({ id: widget.id, days: 14 });
      if (request !== requests) return;
      usage = answer;
      failed = false;
    } catch {
      if (request === requests) failed = true;
    }
  }

  // The budget in force is the server's (the policy may cap it), so a saved
  // change is fetched again rather than shown from the widget.
  let fetchedFor: string | null = null;
  $effect(() => {
    if (!visible) {
      fetchedFor = null;
      return;
    }
    const key = `${widget.id} ${widget.limits.daily_token_budget} ${widget.updated_at}`;
    if (key === fetchedFor) return;
    fetchedFor = key;
    untrack(load);
  });
</script>

<section
  aria-labelledby="widget-usage-title"
  class="border-default bg-primary flex flex-col gap-3 rounded-xl border p-4"
>
  <h2 id="widget-usage-title" class="text-base font-semibold">{m.widget_admin_usage()}</h2>

  {#if failed}
    <p role="alert" class="text-negative-default text-sm">{m.widget_admin_usage_failed()}</p>
  {:else if !usage}
    <p class="text-secondary text-sm" aria-live="polite">{m.loading()}</p>
  {:else}
    <div>
      <div class="flex items-baseline justify-between text-sm">
        <span id="widget-budget-label">{m.widget_admin_budget_today()}</span>
        <span class="text-secondary">
          {m.widget_admin_budget_used({
            used: number.format(usage.budget_used_today),
            budget: number.format(usage.daily_token_budget)
          })}
        </span>
      </div>
      <div
        class="bg-secondary mt-1 h-2 overflow-hidden rounded-full"
        role="progressbar"
        aria-labelledby="widget-budget-label"
        aria-valuemin="0"
        aria-valuemax="100"
        aria-valuenow={budgetPercent}
        aria-valuetext={`${budgetPercent} %`}
      >
        <div
          class={[
            "h-full rounded-full",
            budgetPercent >= 90 ? "bg-negative-default" : "bg-accent-default"
          ]}
          style:width="{budgetPercent}%"
        ></div>
      </div>
    </div>

    {#if days.length === 0}
      <p class="text-secondary text-sm">{m.widget_admin_usage_empty()}</p>
    {:else}
      <Table.Root>
        <caption class="sr-only">{m.widget_admin_usage_caption()}</caption>
        <Table.Header>
          <Table.Row>
            <Table.Head>{m.widget_admin_usage_day()}</Table.Head>
            <Table.Head class="text-right">{m.widget_admin_usage_questions()}</Table.Head>
            <Table.Head class="text-right">{m.widget_admin_usage_tokens_in()}</Table.Head>
            <Table.Head class="text-right">{m.widget_admin_usage_tokens_out()}</Table.Head>
            <Table.Head class="text-right">{m.widget_admin_usage_blocked()}</Table.Head>
            <Table.Head class="text-right">{m.widget_admin_usage_helpful()}</Table.Head>
            <Table.Head class="text-right">{m.widget_admin_usage_unhelpful()}</Table.Head>
          </Table.Row>
        </Table.Header>
        <Table.Body>
          {#each days as row (row.day)}
            <Table.Row>
              <Table.Cell>{day.format(new Date(row.day))}</Table.Cell>
              <Table.Cell class="text-right">{number.format(row.questions)}</Table.Cell>
              <Table.Cell class="text-right">{number.format(row.input_tokens)}</Table.Cell>
              <Table.Cell class="text-right">{number.format(row.output_tokens)}</Table.Cell>
              <Table.Cell class="text-right"
                >{number.format(row.blocked_budget + row.blocked_rate)}</Table.Cell
              >
              <Table.Cell class="text-right">{number.format(row.helpful)}</Table.Cell>
              <Table.Cell class="text-right">{number.format(row.unhelpful)}</Table.Cell>
            </Table.Row>
          {/each}
        </Table.Body>
      </Table.Root>
      <p class="text-secondary text-sm">
        {m.widget_admin_usage_totals({
          questions:
            totals.questions === 1
              ? m.widget_admin_usage_questions_total_one()
              : m.widget_admin_usage_questions_total({ count: number.format(totals.questions) }),
          blocked:
            totals.blocked === 1
              ? m.widget_admin_usage_blocked_total_one()
              : m.widget_admin_usage_blocked_total({ count: number.format(totals.blocked) })
        })}
        {m.widget_admin_usage_feedback_totals({
          helpful: number.format(totals.helpful),
          unhelpful:
            totals.unhelpful === 1
              ? m.widget_admin_usage_unhelpful_total_one()
              : m.widget_admin_usage_unhelpful_total({ count: number.format(totals.unhelpful) })
        })}
      </p>
    {/if}
  {/if}
</section>
