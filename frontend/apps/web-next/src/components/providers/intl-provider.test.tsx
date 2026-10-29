// @vitest-environment jsdom
import { cleanup, render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
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

it("uses a stable Stockholm snapshot for server rendering and hydration", () => {
  const html = renderToString(
    <AppIntlProvider locale="sv" messages={{}}>
      <Clock />
    </AppIntlProvider>
  );
  expect(html).toContain("Europe/Stockholm");
  expect(html).toContain(">21</output>");
});
