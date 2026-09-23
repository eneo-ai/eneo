import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/svelte";
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

vi.mock("$lib/components/toast", () => ({
  toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() }
}));
import { toast } from "$lib/components/toast";
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

describe("FlowRunsTable retry from the failed step", () => {
  it("offers a failed run a retry, sends a stable key, and reports the restart step", async () => {
    let listCalls = 0;
    const { eneo, calls, retryCalls } = makeRunsListEneo(() => {
      listCalls += 1;
      return {
        items: [
          makeFlowRun({ id: "aaa", status: "failed", revision: 4 }),
          makeFlowRun({ id: "bbb", status: "completed" })
        ],
        has_more: false
      };
    });
    renderTable(eneo);
    await waitFor(() => expect(calls).toHaveLength(1));

    const retryButton = await screen.findByTestId("flow-run-retry-aaa");
    expect(screen.queryByTestId("flow-run-retry-bbb")).toBeNull();
    await fireEvent.click(retryButton);

    await waitFor(() => expect(retryCalls).toHaveLength(1));
    expect(retryCalls[0].pathname).toMatch(/\/runs\/aaa\/retry\/$/);
    expect(retryCalls[0].idempotencyKey).toBe("flow-run-retry:aaa:4");
    await waitFor(() => expect(listCalls).toBeGreaterThanOrEqual(2));
    expect(toast.success).toHaveBeenCalledWith(m.flow_run_retry_started({ step: "2" }));
  });

  it("offers the retry in the mobile card as well", async () => {
    const { eneo, retryCalls } = makeRunsListEneo(() => ({
      items: [makeFlowRun({ id: "aaa", status: "failed", revision: 2 })],
      has_more: false
    }));
    renderTable(eneo);
    const list = await screen.findByRole("list", { name: m.flow_history() });
    const mobileButton = await within(list).findByTestId("flow-run-retry-mobile-aaa");
    await fireEvent.click(mobileButton);
    await waitFor(() => expect(retryCalls).toHaveLength(1));
    expect(retryCalls[0].idempotencyKey).toBe("flow-run-retry:aaa:2");
  });

  it("lets Enter on the retry button retry without expanding the row", async () => {
    const { eneo, retryCalls, graphCalls } = makeRunsListEneo(() => ({
      items: [makeFlowRun({ id: "aaa", status: "failed", revision: 1 })],
      has_more: false
    }));
    renderTable(eneo);
    const retryButton = await screen.findByTestId("flow-run-retry-aaa");
    retryButton.focus();
    await fireEvent.keyDown(retryButton, { key: "Enter" });
    // A native button activates on Enter; jsdom does not synthesise that
    // click, so the assertion is that the row did NOT swallow the key.
    await fireEvent.click(retryButton);
    await waitFor(() => expect(retryCalls).toHaveLength(1));
    expect(graphCalls).toHaveLength(0);
    expect(retryButton.closest("tr")?.getAttribute("class")).not.toContain("bg-muted/50");
  });

  it("tells the user when the same key replays an earlier child", async () => {
    vi.mocked(toast.success).mockClear();
    vi.mocked(toast.info).mockClear();
    const { eneo, retryCalls } = makeRunsListEneo(
      () => ({
        items: [makeFlowRun({ id: "aaa", status: "failed", revision: 1 })],
        has_more: false
      }),
      {
        retry: () => ({
          run: makeFlowRun({ id: "retry-child", status: "completed" }),
          created: false,
          source_run_id: "aaa",
          first_executed_step_order: 2,
          reused_step_orders: [1]
        })
      }
    );
    renderTable(eneo);
    await fireEvent.click(await screen.findByTestId("flow-run-retry-aaa"));
    await waitFor(() => expect(retryCalls).toHaveLength(1));
    await waitFor(() => expect(toast.info).toHaveBeenCalledWith(m.flow_run_retry_replayed()));
    expect(toast.success).not.toHaveBeenCalledWith(m.flow_run_retry_started({ step: "2" }));
  });
});

describe("FlowRunsTable row actions", () => {
  it("names the next step for a run waiting for review", async () => {
    const { eneo, calls } = makeRunsListEneo(() => ({
      items: [
        makeFlowRun({ id: "aaa", status: "awaiting_review" }),
        makeFlowRun({ id: "bbb", status: "completed" })
      ],
      has_more: false
    }));
    renderTable(eneo);
    await waitFor(() => expect(calls).toHaveLength(1));

    expect((await screen.findByTestId("flow-run-evidence-toggle-aaa")).textContent).toContain(
      m.flow_run_review_open()
    );
    expect(screen.getByTestId("flow-run-evidence-toggle-bbb").textContent).toContain(
      m.flow_run_show_details()
    );
  });
});

describe("FlowRunsTable search and pagination", () => {
  it("follows step statuses on the poll but loads audited step outputs only on demand", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      const { eneo, calls, graphCalls, stepCalls } = makeRunsListEneo(() => ({
        items: [makeFlowRun({ id: "aaa", status: "running" })],
        has_more: false
      }));
      renderTable(eneo);

      await waitFor(() => expect(calls).toHaveLength(1));
      expect(graphCalls).toHaveLength(0);
      expect(stepCalls).toHaveLength(0);

      await vi.advanceTimersByTimeAsync(30_000);
      expect(graphCalls).toHaveLength(0);
      expect(stepCalls).toHaveLength(0);

      await fireEvent.click(screen.getByTestId("flow-run-evidence-toggle-aaa"));
      await waitFor(() => expect(graphCalls).toHaveLength(1));
      await waitFor(() => expect(stepCalls).toHaveLength(1));

      // Each run-list poll (5 s) re-reads the run-pinned graph so the step
      // statuses move with the row; the audited step list is not re-read.
      await vi.advanceTimersByTimeAsync(30_000);
      await waitFor(() => expect(graphCalls.length).toBeGreaterThanOrEqual(4));
      expect(stepCalls).toHaveLength(1);

      const graphCallsBeforeRefresh = graphCalls.length;
      await fireEvent.click(screen.getByRole("button", { name: m.flow_run_progress_refresh() }));
      await waitFor(() => expect(stepCalls).toHaveLength(2));
      expect(graphCalls.length).toBeGreaterThanOrEqual(graphCallsBeforeRefresh + 1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("moves a step to completed on the poll, marks its unread output stale, then shows evidence", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let listCalls = 0;
      const { eneo, calls, graphCalls, stepCalls, evidenceCalls } = makeRunsListEneo(
        () => {
          listCalls += 1;
          return {
            items: [makeFlowRun({ id: "aaa", status: listCalls >= 4 ? "completed" : "running" })],
            has_more: false
          };
        },
        {
          graph: (call) => ({
            nodes: [
              {
                id: "step-1",
                label: "Summarize",
                type: "llm",
                step_order: 1,
                run_status: call === 1 ? "running" : "completed",
                num_tokens_input: call === 1 ? null : 12,
                num_tokens_output: call === 1 ? null : 34
              }
            ],
            edges: []
          }),
          steps: () => [
            {
              input_text_aliases: [],
              flow_run_id: "aaa",
              flow_id: "flow-1",
              tenant_id: "tenant-1",
              step_id: "step-1",
              step_order: 1,
              status: "running",
              error_message: null,
              created_at: "2026-08-25T09:00:00Z",
              updated_at: "2026-08-25T09:00:01Z"
            }
          ]
        }
      );
      renderTable(eneo);
      await waitFor(() => expect(calls).toHaveLength(1));

      await fireEvent.click(await screen.findByTestId("flow-run-evidence-toggle-aaa"));
      await waitFor(() => expect(stepCalls).toHaveLength(1));
      const panel = () => document.getElementById("flow-run-progress-step-1")!;
      await waitFor(() => expect(panel().textContent).toContain(m.flow_run_status_running()));

      // Next poll: the graph says completed; the audited step list is not re-read.
      await vi.advanceTimersByTimeAsync(5_000);
      await waitFor(() => expect(graphCalls.length).toBeGreaterThanOrEqual(2));
      await waitFor(() => expect(panel().textContent).toContain(m.flow_run_status_completed()));
      expect(panel().textContent).toContain(m.flow_run_progress_details_stale());
      expect(panel().textContent).not.toContain(m.flow_run_progress_empty_output());
      expect(panel().textContent).toContain(m.flow_run_tokens_in({ count: "12" }));
      expect(stepCalls).toHaveLength(1);

      // The run itself completes: the row flips and the audited evidence view takes over.
      await vi.advanceTimersByTimeAsync(10_000);
      await waitFor(() => expect(evidenceCalls).toHaveLength(1));
      expect(stepCalls).toHaveLength(1);
    } finally {
      vi.useRealTimers();
    }
  });

  it("keeps history visible and offers retry when background refresh fails", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    try {
      let requestCount = 0;
      const { eneo, calls } = makeRunsListEneo(() => {
        requestCount += 1;
        if (requestCount === 2) throw new Error("temporary refresh failure");
        return {
          items: [makeFlowRun({ id: "aaa", status: "running" })],
          has_more: false
        };
      });
      renderTable(eneo);

      await waitFor(() => expect(calls).toHaveLength(1));
      await vi.advanceTimersByTimeAsync(5_000);
      await waitFor(() =>
        expect(screen.getByText(m.flow_history_refresh_failed_title())).toBeTruthy()
      );
      expect(screen.getByTestId("flow-run-evidence-toggle-aaa")).toBeTruthy();

      await fireEvent.click(screen.getByRole("button", { name: m.flow_retry() }));
      await waitFor(() => expect(calls).toHaveLength(3));
      await waitFor(() =>
        expect(screen.queryByText(m.flow_history_refresh_failed_title())).toBeNull()
      );
    } finally {
      vi.useRealTimers();
    }
  });

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
        const candidate = mobileList.querySelector(
          'button[data-testid="flow-run-evidence-toggle-mobile-aaa"]'
        );
        expect(candidate).toBeTruthy();
        return candidate as HTMLElement;
      });
      // Collapsed, the panel does not exist, so the button controls nothing.
      expect(toggle.getAttribute("aria-controls")).toBeNull();
      await fireEvent.click(toggle);
      await waitFor(() =>
        expect(toggle.getAttribute("aria-controls")).toBe("flow-run-evidence-aaa")
      );

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
