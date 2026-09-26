// @vitest-environment jsdom
import { cleanup, screen, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";

const run = (id: string, text: string | null, created_at: string) => ({
  id,
  status: "complete",
  input: { text, files: [] },
  created_at
});

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: () =>
      Promise.resolve({
        data: {
          items: [
            run("run-1", "Sammanfatta protokollet", "2026-09-20T08:00:00Z"),
            run("run-2", null, "2026-09-21T09:30:00Z")
          ]
        },
        response: new Response("{}")
      })
  }
}));

import { ResultsTable } from "./results-table";

afterEach(cleanup);

describe("ResultsTable", () => {
  it("names each run's menu by the time its row shows", async () => {
    renderInApp(<ResultsTable appId="app-1" resultHref={(id) => `/apps/app-1/results/${id}`} />);

    const rows = (await screen.findAllByRole("row")).slice(1);
    expect(rows).toHaveLength(2);
    for (const row of rows) {
      // A run has no name of its own: the menu says the time in the row's
      // Skapad cell, as the row writes it.
      const time = within(row).getAllByRole("cell")[2]!.textContent!;
      expect(time).toMatch(/2026/);
      expect(within(row).getByRole("button", { name: `Fler åtgärder för ${time}` })).toBeTruthy();
    }
  });
});
