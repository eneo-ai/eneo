<script lang="ts">
  import { createDateRangePicker } from "@melt-ui/svelte";
  import { CalendarDate, type DateValue } from "@internationalized/date";
  import Button from "$lib/Button/Button.svelte";
  import { Tooltip } from "$lib/Tooltip/index.js";
  import { IconCalendar } from "@intric/icons/calendar";
  import { cva } from "class-variance-authority";
  import { getUIMessage } from "$lib/utils/messages.js";

  const now = new Date();
  const today = new CalendarDate(now.getFullYear(), now.getMonth() + 1, now.getUTCDate());

  let cls = "";
  export { cls as class };

  export let value: {
    start: DateValue | undefined;
    end: DateValue | undefined;
  } = getDefaultRange();

  function getDefaultRange() {
    return {
      start: today.subtract({ weeks: 1 }),
      end: today
    };
  }

  const {
    elements: {
      overlay,
      arrow,
      calendar,
      cell,
      content,
      field,
      grid,
      heading,
      label,
      nextButton,
      prevButton,
      startSegment,
      endSegment,
      trigger
    },
    states: { months, headingValue, weekdays, segmentContents, open },
    helpers: { isDateDisabled, isDateUnavailable, isSelected }
  } = createDateRangePicker({
    defaultValue: value,
    weekdayFormat: "short",
    locale: "en-GB",
    onValueChange: ({ next }: { next: any }) => {
      value = next;
      return next;
    },
    preventScroll: true,
    arrowSize: 12,
    minValue: new CalendarDate(2023, 1, 1),
    maxValue: today
  });

  const calendarCell = cva(
    [
      "relative",
      "z-0",
      "flex",
      "h-10",
      "w-10",
      "cursor-pointer",
      "select-none",
      "items-center",
      "justify-center",
      "rounded",
      "p-4",
      "hover:bg-hover-default",
      "focus:z-10",
      "focus:ring-4",
      "focus:ring-[var(--text-primary)]"
    ],
    {
      variants: {
        highlighted: {
          true: ["bg-accent-dimmer"]
        },
        selected: { true: ["!bg-accent-default", "text-on-fill", "hover:!bg-accent-stronger"] },
        disabled: { true: ["pointer-events-none", "opacity-40"] },
        unavailable: { true: ["text-negative-default", "pointer-events-none", "line-through"] },
        outsideVisibleMonths: {
          true: ["pointer-events-none", "cursor-default", "opacity-40", "hover:bg-transparent"]
        },
        outsideMonth: {
          true: ["pointer-events-none", "cursor-default", "opacity-0", "hover:bg-transparent"]
        },
        rangeHighlighted: { true: ["bg-accent-dimmer"] }
      }
    }
  );

  // When doing "use:field" svelte-check complains about the number of arguments... this "fixes" it for now
  const fieldWrap = (_: unknown) => field(); // eslint-disable-line @typescript-eslint/no-unused-vars
</script>

<div class="flex items-center justify-between gap-4 {cls}">
  <span {...$label} use:label class=""
    >{#if $$slots.default}<slot />{:else}{getUIMessage('ui_select_timeframe')}{/if}</span
  >
  <div
    {...$field}
    use:fieldWrap
    class="data-[invalid]:text-negative-default mt-0 flex items-center gap-1"
  >
    <div
      class="border-default bg-primary ring-default placeholder:text-muted flex h-10 min-w-[220px] items-center justify-between gap-0.5 overflow-hidden rounded-lg border px-3 py-2 text-center font-mono shadow focus-within:ring-2 hover:ring-2 focus-visible:ring-2"
    >
      {#each $segmentContents.start as seg (seg)}
        <div {...$startSegment(seg.part)} use:startSegment>
          {seg.value}
        </div>
      {/each}
      <div aria-hidden="true" class="px-1">–</div>
      {#each $segmentContents.end as seg (seg)}
        <div {...$endSegment(seg.part)} use:endSegment>
          {seg.value}
        </div>
      {/each}
    </div>
    <Tooltip text={getUIMessage('ui_open_calendar')} asFragment let:trigger={tooltipTrigger} placement="top">
      <Button is={[$trigger, ...tooltipTrigger]} variant="primary" padding="icon">
        <IconCalendar />
      </Button>
    </Tooltip>
  </div>
</div>

{#if open}
  <div {...$overlay} use:overlay class="fixed inset-0 z-[90]"></div>
  <div
    {...$content}
    use:content
    class="border-stronger bg-primary relative z-[100] rounded-md border shadow-md"
  >
    <div {...$calendar} use:calendar class="bg-primary relative z-10 rounded-md p-2">
      <header class="flex items-center justify-between pb-2">
        <Button is={[$prevButton]} variant="outlined" class="!px-3">←</Button>
        <div {...$heading} use:heading class="font-mono">
          {$headingValue}
        </div>
        <Button is={[$nextButton]} variant="outlined" class="!px-3">→</Button>
      </header>
      <div>
        {#each $months as month (month)}
          <table {...$grid} use:grid class="w-full">
            <thead aria-hidden="true">
              <tr>
                {#each $weekdays as day (day)}
                  <th>
                    <div>
                      {day}
                    </div>
                  </th>
                {/each}
              </tr>
            </thead>
            <tbody>
              {#each month.weeks as weekDates (weekDates)}
                <tr>
                  {#each weekDates as date (date)}
                    {@const cellInfo = $cell(date, month.value)}
                    <td
                      role="gridcell"
                      aria-disabled={$isDateDisabled(date) || $isDateUnavailable(date)}
                    >
                      <div
                        {...cellInfo}
                        use:cell
                        class={calendarCell({
                          highlighted: cellInfo["data-highlighted"] != null,
                          disabled: cellInfo["data-disabled"] != null,
                          selected: $isSelected(date),
                          unavailable: cellInfo["data-unavailable"] != null,
                          outsideMonth: cellInfo["data-outside-month"] != null,
                          outsideVisibleMonths: cellInfo["data-outside-visible-months"] != null
                        })}
                      >
                        {date.day}
                      </div>
                    </td>
                  {/each}
                </tr>
              {/each}
            </tbody>
          </table>
        {/each}
      </div>
    </div>
    <div {...$arrow} use:arrow class="border-stronger !z-0 border"></div>
  </div>
{/if}
