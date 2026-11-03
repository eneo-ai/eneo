// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { useFormatter, useTimeZone } from "use-intl";
import { afterEach, expect, it } from "vitest";
import { AppIntlProvider } from "./intl-provider";

afterEach(cleanup);

function Clock() {
  const format = useFormatter();
  return (
    <>
      <output aria-label="zone">{useTimeZone()}</output>
      <output aria-label="hour">
        {format.dateTime(new Date("2026-01-01T20:00:00Z"), { hour: "numeric" })}
      </output>
    </>
  );
}

it("formats timestamps in the viewer's zone", () => {
  render(
    <AppIntlProvider locale="sv" messages={{}}>
      <Clock />
    </AppIntlProvider>
  );
  expect(screen.getByLabelText("zone").textContent).toBe(
    Intl.DateTimeFormat().resolvedOptions().timeZone
  );
  expect(screen.getByLabelText("hour").textContent).toBe("01");
});
