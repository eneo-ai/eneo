import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import type { Eneo, FlowRun } from "@eneo/eneo-js";
import { readable } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import { makeFlowRun, makeRunsListEneo, makeTestFlow } from "./flowRunHistoryTestFixtures";

vi.mock("$lib/features/flows/FlowUserMode", () => ({
  getFlowUserMode: () => readable("user")
}));

import FlowRunsTable from "./FlowRunsTable.svelte";

function run(id: string, created: string): FlowRun {
  return makeFlowRun({
    id,
    created_at: created,
    updated_at: created,
    input_payload_json: { arende: `Ärende ${id}` }
  });
}

function renderTable(eneo: Eneo) {
  render(FlowRunsTable, {
    props: {
      flow: makeTestFlow(),
      eneo,
      visible: true,
      optimisticRuns: [],
      reloadTrigger: 0
    }
  });
}

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});

describe("FlowRunsTable render boundary", () => {
  it("reveals rows across the 100-row render boundary without extra fetches", async () => {
    // 150 backend rows in three 50-row pages. After loading them all, a
    // search+clear resets the render budget to 100; the footer action must
    // reveal the remaining 50 WITHOUT another backend request (the old bug
    // required a second click for fetched rows; render paging must not
    // reintroduce hidden fetched rows).
    const pages = Array.from({ length: 3 }, (_, pageIndex) => ({
      items: Array.from({ length: 50 }, (_, i) =>
        run(
          `p${pageIndex}-r${i}`,
          `2026-08-2${5 - pageIndex}T0${9 - Math.floor(i / 10)}:0${i % 10}:00Z`
        )
      ),
      has_more: pageIndex < 2
    }));
    const { eneo, calls } = makeRunsListEneo((url) => {
      const offset = Number(url.searchParams.get("offset") ?? "0");
      return pages[Math.min(Math.floor(offset / 50), pages.length - 1)];
    });
    renderTable(eneo);
    await waitFor(() => expect(calls).toHaveLength(1));
    const search = await screen.findByLabelText(m.flow_history_search_placeholder());

    const rendered = () => document.querySelectorAll("table tbody tr").length;
    const loadMore = () => screen.getByRole("button", { name: m.flow_history_load_more() });
    await fireEvent.click(loadMore());
    await waitFor(() => expect(rendered()).toBeGreaterThanOrEqual(100));
    await fireEvent.click(loadMore());
    await waitFor(() => expect(calls).toHaveLength(3));
    // Every fetched row is visible after its own click (no second click).
    await waitFor(() =>
      expect(document.querySelectorAll("table tbody tr").length).toBeGreaterThanOrEqual(150)
    );

    // Reset the render budget via a search round-trip.
    await fireEvent.input(search, { target: { value: "p2-r49" } });
    await waitFor(() =>
      expect(screen.getByText((content) => content.includes("Visar 1"))).toBeTruthy()
    );
    await fireEvent.input(search, { target: { value: "" } });
    await waitFor(() =>
      expect(screen.getByText((content) => content.includes("Visar 100 av 150"))).toBeTruthy()
    );

    const requestsBefore = calls.length;
    await fireEvent.click(loadMore());
    await waitFor(() =>
      expect(document.querySelectorAll("table tbody tr").length).toBeGreaterThanOrEqual(150)
    );
    // Revealing already-loaded rows is render paging, not a backend fetch.
    expect(calls).toHaveLength(requestsBefore);
  });
});
