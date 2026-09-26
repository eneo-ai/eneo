// @vitest-environment jsdom
import { cleanup, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { afterEach, describe, expect, it } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { ClientTime } from "./client-time";

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
