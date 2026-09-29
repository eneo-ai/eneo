import { describe, expect, it, vi } from "vitest";
import { page, userEvent } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { getLocalTimeZone, today, type DateValue } from "@internationalized/date";
import { m } from "$lib/paraglide/messages";
import DateRangePicker from "./DateRangePicker.svelte";

function dayInCurrentMonth(day: number) {
  const match = [...document.querySelectorAll<HTMLElement>("[data-bits-day]")].find(
    (element) =>
      !element.hasAttribute("data-outside-month") && element.textContent?.trim() === String(day)
  );
  if (!match) throw new Error(`day ${day} not rendered`);
  return page.elementLocator(match);
}

describe("DateRangePicker", () => {
  it("shows the default label and the last week as the initial range", async () => {
    render(DateRangePicker, {});

    await expect.element(page.getByText(m.ui_select_timeframe())).toBeVisible();
    await expect.element(page.getByRole("button", { name: m.ui_open_calendar() })).toBeVisible();
  });

  it("commits a range picked in the calendar and closes it", async () => {
    const onValueCommit = vi.fn();
    const now = today(getLocalTimeZone());
    render(DateRangePicker, {
      value: { start: undefined, end: undefined },
      onValueCommit
    });

    await page.getByRole("button", { name: m.ui_open_calendar() }).click();
    await dayInCurrentMonth(1).click();
    await dayInCurrentMonth(now.day).click();

    await vi.waitFor(() => expect(onValueCommit).toHaveBeenCalledTimes(1));
    const range = onValueCommit.mock.calls[0][0] as { start: DateValue; end: DateValue };
    expect(range.start.toString()).toBe(now.set({ day: 1 }).toString());
    expect(range.end.toString()).toBe(now.toString());
    await vi.waitFor(() => expect(document.querySelector("[data-bits-day]")).toBeNull());
  });

  it("treats a lone start date as a single-day range when the calendar closes", async () => {
    const onValueCommit = vi.fn();
    const now = today(getLocalTimeZone());
    render(DateRangePicker, {
      value: { start: undefined, end: undefined },
      onValueCommit
    });

    await page.getByRole("button", { name: m.ui_open_calendar() }).click();
    await dayInCurrentMonth(1).click();
    await userEvent.keyboard("{Escape}");

    await vi.waitFor(() => expect(onValueCommit).toHaveBeenCalledTimes(1));
    const range = onValueCommit.mock.calls[0][0] as { start: DateValue; end: DateValue };
    expect(range.start.toString()).toBe(now.set({ day: 1 }).toString());
    expect(range.end.toString()).toBe(range.start.toString());
  });
});
