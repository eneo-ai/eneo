// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";
import { renderInApp } from "@/test/render";
import { StartRunSummary } from "./start-run-summary";

afterEach(cleanup);

describe("StartRunSummary", () => {
  it("shows a date as the calendar showed it, not as the stored value", () => {
    renderInApp(
      <StartRunSummary
        summary={{
          runLabel: null,
          fields: [
            {
              field: { name: "datum", label: "Datum", type: "date", required: true, order: 1 },
              value: "2026-11-12"
            }
          ],
          freeText: null,
          files: []
        }}
        takesInput
        headingRef={null}
        notices={null}
      />
    );
    expect(screen.getByText("12 november 2026")).toBeTruthy();
    expect(screen.queryByText("2026-11-12")).toBeNull();
  });
});
