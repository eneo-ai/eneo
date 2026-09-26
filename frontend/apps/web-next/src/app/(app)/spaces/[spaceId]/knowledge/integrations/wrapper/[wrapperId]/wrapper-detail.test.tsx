// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import type { Space } from "@/features/spaces/space";

vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", async () => {
  const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
  const { makeIntegration, makeSpace } = await import("@/features/spaces/testing/space-fixture");
  const folder = { wrapper_id: "w1", wrapper_name: "Byggnad" };
  return {
    useSpace: () =>
      useSpaceFromQuery(
        () =>
          makeSpace({
            integrations: [
              makeIntegration({ id: "i1", name: "Mall 1", ...folder }),
              makeIntegration({ id: "i2", name: "Mall 2", ...folder })
            ]
          }) as Space
      )
  };
});
vi.mock("@/features/jobs/use-jobs", () => ({
  useJobs: () => ({ trackJob: () => {}, queueUploads: () => {} })
}));
vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () => Promise.resolve({ data: { items: [] }, response: new Response("{}") })
  }
}));

import { WrapperDetail } from "./wrapper-detail.client";

afterEach(cleanup);

describe("WrapperDetail", () => {
  it("names the folder's table after the folder", async () => {
    const { container } = renderInApp(<WrapperDetail wrapperId="w1" />);

    const heading = screen.getByRole("heading", { level: 1, name: "Byggnad" });
    const table = screen.getByRole("table", { name: "Byggnad" });
    expect(table.getAttribute("aria-labelledby")).toBe(heading.id);
    expect(within(table).getByText("Mall 1")).toBeTruthy();
    expect(within(table).getByText("Mall 2")).toBeTruthy();
    await expectNoAxeViolations(container);
  });
});
