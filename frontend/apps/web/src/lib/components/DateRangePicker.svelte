<script lang="ts">
  import type { Snippet } from "svelte";
  import { DateRangeField } from "bits-ui";
  import { CalendarDate, getLocalTimeZone, today, type DateValue } from "@internationalized/date";
  import { IconCalendar } from "@eneo/icons/calendar";
  import { buttonVariants } from "$lib/components/ui/button/index.js";
  import * as Popover from "$lib/components/ui/popover/index.js";
  import { RangeCalendar } from "$lib/components/ui/range-calendar/index.js";
  import { getLocale } from "$lib/paraglide/runtime";
  import { m } from "$lib/paraglide/messages";
  import { cn } from "$lib/utils.js";

  type Range = { start: DateValue | undefined; end: DateValue | undefined };

  type Props = {
    value?: Range;
    /** Called when a complete range (both start and end) is selected */
    onValueCommit?: (range: { start: DateValue; end: DateValue }) => void;
    class?: string;
    /** Visible label; defaults to "Select timeframe" */
    children?: Snippet;
  };

  const now = today(getLocalTimeZone());
  const minValue = new CalendarDate(2023, 1, 1);

  let {
    value = $bindable({ start: now.subtract({ weeks: 1 }), end: now }),
    onValueCommit,
    class: className,
    children
  }: Props = $props();

  const locale = $derived(getLocale() === "sv" ? "sv-SE" : "en-GB");

  let calendarOpen = $state(false);
  let pendingStart = $state<DateValue | undefined>();

  function commit(range: Range) {
    value = range;
    if (range.start && range.end) {
      onValueCommit?.({ start: range.start, end: range.end });
    }
  }

  function selectFromCalendar(range: Range) {
    pendingStart = undefined;
    commit(range);
    if (range.start && range.end) calendarOpen = false;
  }

  // Closing the calendar with only a start date selected keeps it as a single-day range.
  function handleCalendarOpenChange(open: boolean) {
    if (open || !pendingStart) return;
    const start = pendingStart;
    pendingStart = undefined;
    commit({ start, end: start });
  }
</script>

<div class={cn("flex items-center justify-between gap-4", className)}>
  <DateRangeField.Root
    bind:value={() => value, commit}
    {minValue}
    maxValue={now}
    {locale}
    class="group flex items-center gap-4"
  >
    <DateRangeField.Label>
      {#if children}{@render children()}{:else}{m.ui_select_timeframe()}{/if}
    </DateRangeField.Label>
    <div class="flex items-center gap-1">
      <div
        class="border-input bg-background focus-within:border-ring focus-within:ring-ring/50 flex h-8 min-w-[220px] items-center justify-center gap-0.5 rounded-lg border px-3 font-mono text-sm focus-within:ring-3 group-data-[invalid]:border-destructive"
      >
        {#each ["start", "end"] as const as type (type)}
          <DateRangeField.Input {type} class="flex items-center">
            {#snippet children({ segments })}
              {#each segments as { part, value: segmentValue }, index (index)}
                <DateRangeField.Segment
                  {part}
                  class="focus:bg-accent-dimmer focus:text-accent-stronger rounded-sm px-0.5 outline-none aria-[valuetext=Empty]:text-muted"
                >
                  {segmentValue}
                </DateRangeField.Segment>
              {/each}
            {/snippet}
          </DateRangeField.Input>
          {#if type === "start"}
            <div aria-hidden="true" class="px-1">–</div>
          {/if}
        {/each}
      </div>
      <Popover.Root bind:open={calendarOpen} onOpenChange={handleCalendarOpenChange}>
        <Popover.Trigger class={buttonVariants({ size: "icon" })} aria-label={m.ui_open_calendar()}>
          <IconCalendar />
        </Popover.Trigger>
        <Popover.Content class="w-auto p-0" align="end">
          <RangeCalendar
            bind:value={() => value, selectFromCalendar}
            onStartValueChange={(start) => (pendingStart = start)}
            {minValue}
            maxValue={now}
            {locale}
          />
        </Popover.Content>
      </Popover.Root>
    </div>
  </DateRangeField.Root>
</div>
