import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import type { Eneo, FlowRun } from "@eneo/eneo-js";
import { readable } from "svelte/store";
import { afterEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import {
  makeFlowRun,
  makeRunsListEneo,
  makeTestFlow,
  setTestViewportMobile
} from "./flowRunHistoryTestFixtures";

const userMode = vi.hoisted(() => ({ current: "user" as "user" | "power_user" }));
vi.mock("$lib/features/flows/FlowUserMode", () => ({
  getFlowUserMode: () => readable(userMode.current)
}));

// The retained-window budget is a pure constant the UI derives from; a small
// value lets the cap states render without mounting 1,000 jsdom rows. The
// window-full copy is parameterized on the same constant, so the rendered
// text stays consistent with the mocked budget.
vi.mock("./flowRunHistoryState", async (importOriginal) => {
  const original = await importOriginal<typeof import("./flowRunHistoryState")>();
  return { ...original, MAX_LOADED_FLOW_RUNS: 3 };
});

import FlowRunsTable from "./FlowRunsTable.svelte";

function run(id: string, created: string): FlowRun {
  return makeFlowRun({
    id,
    created_at: created,
    updated_at: created,
    input_payload_json: { arende: `Ärende ${id}` }
  });
}

/**
 * The REAL generated client over a fake fetch transport: request routing and
 * response decoding stay the SDK's own, so the fixture cannot drift from the
 * generated contract.
 */
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

describe("FlowRunsTable search and pagination", () => {
  it("keeps the load-more action reachable when a search has zero matches", async () => {
    const { eneo, calls } = makeRunsListEneo(() => ({
      items: [run("aaa", "2026-08-25T09:00:00Z")],
      has_more: true
    }));
    renderTable(eneo);
    await waitFor(() => expect(calls).toHaveLength(1));
    const search = await screen.findByLabelText(m.flow_history_search_placeholder());
    await fireEvent.input(search, { target: { value: "finns-verkligen-inte" } });
    await waitFor(() => expect(screen.getByText(m.flow_history_no_search_matches())).toBeTruthy());

    const loadMore = screen.getByRole("button", { name: m.flow_history_load_more() });
    await fireEvent.click(loadMore);
    await waitFor(() => expect(calls).toHaveLength(2));
    expect(calls[1]).toMatchObject({ offset: 1 });
  });

  it("connects the search field to the scope hint for assistive tech", async () => {
    const { eneo, calls } = makeRunsListEneo(() => ({
      items: [run("aaa", "2026-08-25T09:00:00Z")],
      has_more: true
    }));
    renderTable(eneo);
    await waitFor(() => expect(calls).toHaveLength(1));
    const search = await screen.findByLabelText(m.flow_history_search_placeholder());
    expect(search.getAttribute("aria-describedby")).toBeNull();

    await fireEvent.input(search, { target: { value: "aaa" } });
    await waitFor(() => expect(search.getAttribute("aria-describedby")).toBeTruthy());
    const describedBy = search.getAttribute("aria-describedby");
    const hint = document.getElementById(describedBy ?? "");
    expect(hint?.textContent).toContain("1");
  });

  it("offers no dead load-more action at the retained-window budget", async () => {
    const fullWindow = Array.from({ length: 3 }, (_, i) => run(`r${i}`, "2026-08-25T09:00:00Z"));
    const { eneo, calls } = makeRunsListEneo(() => ({ items: fullWindow, has_more: true }));
    renderTable(eneo);
    await waitFor(() => expect(calls).toHaveLength(1));
    const search = await screen.findByLabelText(m.flow_history_search_placeholder());
    await fireEvent.input(search, { target: { value: "finns-verkligen-inte" } });
    await waitFor(() => expect(screen.getByText(m.flow_history_no_search_matches())).toBeTruthy());

    // At the cap the zero-match state explains the bound instead of
    // offering an action every click would reject; the copy carries the
    // same (mocked) constant the UI derives from.
    expect(screen.queryByRole("button", { name: m.flow_history_load_more() })).toBeNull();
    expect(screen.getAllByText(m.flow_history_window_full({ count: "3" })).length).toBeGreaterThan(
      0
    );
    const describedBy = search.getAttribute("aria-describedby");
    const hint = document.getElementById(describedBy ?? "");
    expect(hint?.textContent).toContain("3");
  });

  it("expands a mobile run into ONE detail mount that enforces the care-data policy", async () => {
    setTestViewportMobile(true);
    // The export toolbar (the sensitive-gated surface) renders in the
    // power-user mode.
    userMode.current = "power_user";
    try {
      const { eneo, calls, evidenceCalls } = makeRunsListEneo(() => ({
        items: [makeFlowRun({ id: "aaa", status: "completed" })],
        has_more: false
      }));
      render(FlowRunsTable, {
        props: {
          flow: makeTestFlow(),
          careDataPolicy: {
            sensitive: true,
            approvalMode: null,
            preApprovalVisibility: null
          },
          eneo,
          visible: true,
          optimisticRuns: [],
          reloadTrigger: 0
        }
      });
      await waitFor(() => expect(calls).toHaveLength(1));

      // Interact with the MOBILE tree specifically: the toggle inside the
      // history card list, not the desktop table row.
      const mobileList = await screen.findByRole("list", { name: m.flow_history() });
      const toggle = await waitFor(() => {
        const candidate = mobileList.querySelector('button[aria-controls="flow-run-evidence-aaa"]');
        expect(candidate).toBeTruthy();
        return candidate as HTMLElement;
      });
      await fireEvent.click(toggle);

      // Exactly one detail mount and exactly one evidence request.
      await waitFor(() => expect(evidenceCalls).toHaveLength(1));
      expect(document.querySelectorAll('[id="flow-run-evidence-aaa"]')).toHaveLength(1);

      // The sensitive-care policy suppresses export actions and shows the
      // explanatory badge instead.
      await waitFor(() =>
        expect(screen.getByText(m.flow_sensitive_evidence_export_disabled())).toBeTruthy()
      );
      expect(
        screen.queryByRole("button", { name: m.flow_run_download_evidence_export() })
      ).toBeNull();
    } finally {
      setTestViewportMobile(false);
      userMode.current = "user";
    }
  });

  it("surfaces a nonfatal load-more failure with a retry that keeps the table", async () => {
    let failNext = true;
    const { eneo, calls } = makeRunsListEneo((url) => {
      const offset = Number(url.searchParams.get("offset") ?? "0");
      if (offset > 0 && failNext) {
        failNext = false;
        throw new Error("boom");
      }
      return offset === 0
        ? { items: [run("aaa", "2026-08-25T09:00:00Z")], has_more: true }
        : { items: [run("bbb", "2026-08-24T09:00:00Z")], has_more: false };
    });
    renderTable(eneo);
    await waitFor(() => expect(calls).toHaveLength(1));

    const loadMore = await screen.findByRole("button", { name: m.flow_history_load_more() });
    await fireEvent.click(loadMore);
    await waitFor(() => expect(screen.getByText(m.flow_history_load_more_failed())).toBeTruthy());
    // The loaded history stays visible behind the inline error.
    expect(screen.queryByText(m.flow_history_load_failed_title())).toBeNull();

    const retry = screen.getByRole("button", { name: m.flow_retry() });
    await fireEvent.click(retry);
    await waitFor(() => expect(calls).toHaveLength(3));
    // The retry reuses the same backend offset.
    expect(calls[1].offset).toBe(calls[2].offset);
  });
});
