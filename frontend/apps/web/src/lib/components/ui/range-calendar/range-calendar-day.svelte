<script lang="ts">
  import { RangeCalendar as RangeCalendarPrimitive } from "bits-ui";
  import { cn } from "$lib/utils.js";

  let {
    ref = $bindable(null),
    class: className,
    ...restProps
  }: RangeCalendarPrimitive.DayProps = $props();
</script>

<!-- NOTE: `bg-accent-default`/`text-on-fill` instead of upstream's `bg-primary`/`text-primary-foreground`
  — see app.css `--color-primary` namespace conflict comment. -->
<RangeCalendarPrimitive.Day
  bind:ref
  class={cn(
    "flex size-(--cell-size) flex-col items-center justify-center gap-1 rounded-(--cell-radius) p-0 leading-none font-normal whitespace-nowrap select-none",
    "not-data-selected:hover:bg-accent/50 not-data-selected:hover:text-accent-foreground",
    "data-[range-middle]:rounded-none [&[data-today]:not([data-selected])]:bg-accent [&[data-today]:not([data-selected])]:text-accent-foreground [&[data-today][data-disabled]]:text-muted-foreground",
    // range Start
    "data-[range-start]:bg-accent-default data-[range-start]:text-on-fill data-[range-start]:hover:text-on-fill",
    // range End
    "data-[range-end]:bg-accent-default data-[range-end]:text-on-fill data-[range-end]:hover:text-on-fill",
    // Outside months
    "[&[data-outside-month]:not([data-selected])]:text-muted-foreground [&[data-outside-month]:not([data-selected])]:hover:text-accent-foreground",
    // Disabled
    "data-[disabled]:pointer-events-none data-[disabled]:text-muted-foreground data-[disabled]:opacity-50",
    // Unavailable
    "data-[unavailable]:line-through",
    "dark:data-[range-middle]:hover:bg-accent/0",
    // focus
    "focus:relative focus:border-ring focus:ring-ring/50",
    // inner spans
    "[&>span]:text-xs [&>span]:opacity-70",
    className
  )}
  {...restProps}
/>
