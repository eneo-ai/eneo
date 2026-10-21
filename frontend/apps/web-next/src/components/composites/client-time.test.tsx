// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ClientTime, useClientTimeText } from "./client-time";

afterEach(cleanup);

// 08:30 UTC is 25 September in every time zone the tests run in.
const VALUE = "2026-09-25T08:30:00Z";

describe("ClientTime", () => {
  it("renders nothing on the server, so its markup cannot differ from the client's", () => {
    expect(renderToString(<ClientTime value={VALUE} format="date_time" />)).toBe("");
  });

  it("writes the date in the viewer's locale once hydrated", async () => {
    const { container } = renderInApp(
      <p>
        <ClientTime value={VALUE} format="date_time" />
      </p>
    );
    expect(screen.getByText(/^25 sep\. 2026/)).toBeTruthy();
    await expectNoAxeViolations(container);
  });
});

describe("useClientTimeText", () => {
  function Label({ format }: { format: "date" | "date_long" | "date_time" }) {
    return <span>{useClientTimeText(VALUE, format) ?? "–"}</span>;
  }

  it("is null on the server, like ClientTime, and without a valid value", () => {
    expect(renderToString(<Label format="date_time" />)).toBe("<span>–</span>");
    function Missing({ value }: { value: string | null }) {
      return <span>{useClientTimeText(value, "date_time") ?? "–"}</span>;
    }
    renderInApp(
      <>
        <Missing value={null} />
        <Missing value="inte ett datum" />
      </>
    );
    expect(screen.getAllByText("–")).toHaveLength(2);
  });

  it("writes the text ClientTime shows, for names and labels", () => {
    for (const format of ["date", "date_long", "date_time"] as const) {
      const shown = renderInApp(<ClientTime value={VALUE} format={format} />).container.textContent;
      cleanup();
      const text = renderInApp(<Label format={format} />).container.textContent;
      cleanup();
      expect(shown).toMatch(/2026/);
      expect(text).toBe(shown);
    }
  });
});
