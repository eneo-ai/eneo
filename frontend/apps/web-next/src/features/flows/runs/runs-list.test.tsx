// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { router } from "@/test/navigation";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { makeRunDetail, makeRunSummary } from "./run-fixtures";
import type { RunListItem } from "./runs-api";

const state = vi.hoisted(() => ({
  announce: vi.fn(),
  toast: { success: vi.fn(), info: vi.fn(), warning: vi.fn(), error: vi.fn() },
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("../editor/testing/fixtures").apiStub>
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub } = await import("../editor/testing/fixtures");
  state.stub = apiStub(new Proxy({}, { get: (_target, key: string) => state.routes[key] }));
  return { browserApi: state.stub.client };
});
vi.mock("@/lib/toast", () => ({ toast: state.toast }));
vi.mock("@/lib/navigation", () => import("@/test/navigation"));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => state.announce
}));

import { FlowRunsList } from "./runs-list";
import { rememberStartedRun } from "./runs-optimistic";

const LIST = "GET /api/v1/flows/{id}/runs/";
const REDISPATCH = "POST /api/v1/flows/{id}/runs/{run_id}/redispatch/";
const RETRY = "POST /api/v1/flows/{id}/runs/{run_id}/retry/";
const CANCEL = "POST /api/v1/flows/{id}/runs/{run_id}/cancel/";

/** The list of a flow whose published version is 3, the fixtures' version. */
function List() {
  return <FlowRunsList flowId="flow-1" spaceRouteId="space-1" publishedVersion={3} />;
}

const NO_COUNTS = {
  queued: 0,
  running: 0,
  awaiting_review: 0,
  completed: 0,
  failed: 0,
  cancelled: 0
};

function answerList(items: RunListItem[], hasMore = false, statusCounts = NO_COUNTS) {
  state.routes[LIST] = () => ({
    body: { count: items.length, items, has_more: hasMore, status_counts: statusCounts }
  });
}

/** The query every list read sends: newest start first unless sorted otherwise. */
const FIRST_PAGE = { limit: 25, offset: 0, sort: "started_at", order: "desc" };

function listCalls() {
  return state.stub.calls.filter((call) => `${call.method} ${call.path}` === LIST);
}

beforeEach(() => {
  state.routes = {};
});

afterEach(() => {
  cleanup();
  state.stub.calls.length = 0;
  vi.clearAllMocks();
  vi.useRealTimers();
});

describe("FlowRunsList", () => {
  it("lists the runs with status, start, who started them, duration and version", async () => {
    answerList([
      makeRunSummary({ id: "run-2", status: "failed" }),
      makeRunSummary({
        id: "run-1",
        principal_type: "service_key",
        started_by: {
          principal_type: "service_key",
          id: "service-1",
          display_name: "Ärendeintag",
          email: null
        },
        purpose: "test"
      }),
      makeRunSummary({ id: "run-0", principal_type: "service_key", started_by: null })
    ]);
    const { container } = renderInApp(<List />);

    const table = await screen.findByRole("table", { name: messages.flow_runs_heading });
    const rows = within(table).getAllByRole("row");
    expect(rows).toHaveLength(4);
    expect(within(rows[1]!).getByText(messages.flow_runs_status_failed)).toBeTruthy();
    expect(within(rows[1]!).getByText("1 min 5 s")).toBeTruthy();
    expect(within(rows[1]!).getByText("Version 3")).toBeTruthy();
    expect(within(rows[1]!).getByText("Anna Lind")).toBeTruthy();
    expect(within(rows[2]!).getByText("Ärendeintag")).toBeTruthy();
    // A backend that names no one still says what kind of principal it was.
    expect(within(rows[3]!).getByText(messages.flow_runs_started_by_service_key)).toBeTruthy();
    expect(within(rows[2]!).getByText(messages.flow_runs_purpose_test)).toBeTruthy();
    const link = within(rows[1]!).getByRole("link");
    expect(link.getAttribute("href")).toBe("/spaces/space-1/flows/flow-1/runs/run-2");
    await expectNoAxeViolations(container);
  });

  it("says when there are no runs yet", async () => {
    answerList([]);
    const { container } = renderInApp(<List />);
    expect(await screen.findByText(messages.flow_runs_empty_title)).toBeTruthy();
    expect(screen.getByText(messages.flow_runs_empty_description)).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("shows page usage with missing, zero and incomplete measurements without detail reads", async () => {
    answerList([
      {
        ...makeRunSummary({ id: "with-usage" }),
        token_usage: {
          num_tokens_input: 1000,
          num_tokens_output: 200,
          num_tokens_total: 1200,
          input_completeness: "complete",
          output_completeness: "incomplete"
        },
        transcription_usage: { audio_seconds: 65, completeness: "incomplete" }
      },
      {
        ...makeRunSummary({ id: "zero-usage" }),
        token_usage: {
          num_tokens_input: 0,
          num_tokens_output: 0,
          num_tokens_total: 0,
          input_completeness: "complete",
          output_completeness: "complete"
        }
      },
      makeRunSummary({ id: "without-usage" })
    ]);
    const { container } = renderInApp(<List />);
    const table = await screen.findByRole("table");
    expect(
      within(table).getByRole("columnheader", { name: messages.flow_runs_usage_heading })
    ).toBeTruthy();
    const rows = within(table).getAllByRole("row");
    expect(
      within(rows[1]!).getByText(/1\s200 totalt \(1\s000 in, 200 ut\).*ofullständigt/)
    ).toBeTruthy();
    expect(within(rows[1]!).getByText(/1 min 5 s.*ofullständigt/)).toBeTruthy();
    expect(within(rows[2]!).getByText("0 totalt (0 in, 0 ut)")).toBeTruthy();
    expect(within(rows[3]!).queryByText(/totalt/)).toBeNull();
    expect(within(rows[3]!).getByText(messages.flow_runs_usage_not_recorded)).toBeTruthy();
    expect(state.stub.calls).toHaveLength(1);
    expect(listCalls()).toHaveLength(1);
    await expectNoAxeViolations(container);
  });

  it("says to publish a flow that has no runs and is not published", async () => {
    answerList([]);
    renderInApp(<FlowRunsList flowId="flow-1" spaceRouteId="space-1" publishedVersion={null} />);
    expect(await screen.findByText(messages.flow_runs_empty_description_unpublished)).toBeTruthy();
    expect(screen.queryByText(messages.flow_runs_empty_description)).toBeNull();
  });

  it("asks for the caller's own runs only when asked", async () => {
    answerList([makeRunSummary()]);
    renderInApp(<List />);
    await screen.findByRole("table");
    expect(listCalls()[0]?.init.params?.query).toEqual(FIRST_PAGE);

    fireEvent.click(screen.getByRole("checkbox", { name: messages.flow_runs_only_mine }));
    await vi.waitFor(() =>
      expect(listCalls().at(-1)?.init.params?.query).toEqual({ ...FIRST_PAGE, mine: true })
    );
  });

  it("asks the list endpoint for one status and says when none has it", async () => {
    answerList([makeRunSummary()]);
    const { container } = renderInApp(<List />);
    await screen.findByRole("table");

    answerList([]);
    fireEvent.click(screen.getByRole("combobox", { name: messages.flow_run_extras_status_filter }));
    fireEvent.click(
      await screen.findByRole("option", { name: `${messages.flow_runs_status_failed} (0)` })
    );
    await vi.waitFor(() =>
      expect(listCalls().at(-1)?.init.params?.query).toEqual({
        ...FIRST_PAGE,
        status: ["failed"]
      })
    );
    expect(
      await screen.findByText(
        messages.flow_run_extras_status_empty_title.replace(
          "{status}",
          messages.flow_runs_status_failed
        )
      )
    ).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("names a run by its name, with its start time under it", async () => {
    answerList([makeRunSummary({ id: "run-9", run_label: "Ärende 42" })]);
    renderInApp(<List />);
    const link = await screen.findByRole("link", { name: "Ärende 42" });
    expect(link.getAttribute("href")).toBe("/spaces/space-1/flows/flow-1/runs/run-9");
  });

  it("searches the runs by name or starter once the typing stops", async () => {
    answerList([makeRunSummary()]);
    const { container } = renderInApp(<List />);
    await screen.findByRole("table");

    answerList([]);
    fireEvent.change(screen.getByRole("textbox", { name: messages.flow_run_journey_search }), {
      target: { value: "  ärende " }
    });
    await vi.waitFor(() =>
      expect(listCalls().at(-1)?.init.params?.query).toEqual({ ...FIRST_PAGE, search: "ärende" })
    );
    expect(
      await screen.findByText(
        messages.flow_run_journey_search_empty_title.replace("{search}", "ärende")
      )
    ).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("asks the list endpoint to sort by the column header", async () => {
    answerList([makeRunSummary()]);
    renderInApp(<List />);
    const table = await screen.findByRole("table");

    fireEvent.click(
      within(table).getByRole("button", { name: new RegExp(messages.flow_runs_column_status) })
    );
    await vi.waitFor(() =>
      expect(listCalls().at(-1)?.init.params?.query).toMatchObject({ sort: "status" })
    );
  });

  it("counts the runs per status in the status filter", async () => {
    answerList([makeRunSummary({ status: "failed" })], false, {
      ...NO_COUNTS,
      completed: 12,
      failed: 2
    });
    renderInApp(<List />);
    await screen.findByRole("table");

    fireEvent.click(screen.getByRole("combobox", { name: messages.flow_run_extras_status_filter }));
    expect(
      await screen.findByRole("option", { name: `${messages.flow_runs_status_failed} (2)` })
    ).toBeTruthy();
    expect(
      screen.getByRole("option", { name: `${messages.flow_run_extras_status_any} (14)` })
    ).toBeTruthy();
  });

  it("polls while a run moves, announces the change, then stops", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    answerList([makeRunSummary({ status: "running", finished_at: null, revision: 1 })]);
    renderInApp(<List />);
    const table = await screen.findByRole("table");
    expect(within(table).getByText(messages.flow_runs_status_running)).toBeTruthy();
    expect(listCalls()).toHaveLength(1);

    answerList([makeRunSummary({ status: "completed", revision: 2 })]);
    await act(() => vi.advanceTimersByTimeAsync(2_100));
    // The status filter's options share the status names; the table is what changed.
    await within(table).findByText(messages.flow_runs_status_completed);
    expect(listCalls()).toHaveLength(2);
    expect(state.announce).toHaveBeenCalledWith(
      messages.flow_runs_status_changed.replace("{status}", messages.flow_runs_status_completed)
    );

    await act(() => vi.advanceTimersByTimeAsync(20_000));
    expect(listCalls()).toHaveLength(2);
  });

  it("says how long a run still going has gone on so far", async () => {
    answerList([
      makeRunSummary({
        status: "running",
        started_at: new Date(Date.now() - 65_000).toISOString(),
        finished_at: null
      })
    ]);
    renderInApp(<List />);
    const table = await screen.findByRole("table");
    const so = messages.flow_run_more_elapsed.replace("{time}", "");
    expect(within(table).getByText(new RegExp(`^1 min [56] s${so}$`))).toBeTruthy();
  });

  it("does not poll a list where every run has ended", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    answerList([makeRunSummary({ status: "completed" })]);
    renderInApp(<List />);
    await screen.findByText(messages.flow_runs_status_completed);
    await act(() => vi.advanceTimersByTimeAsync(20_000));
    expect(listCalls()).toHaveLength(1);
  });

  it("reads older runs a page at a time", async () => {
    answerList([makeRunSummary()], true);
    renderInApp(<List />);
    fireEvent.click(await screen.findByRole("button", { name: messages.flow_runs_show_more }));
    await vi.waitFor(() =>
      expect(listCalls().at(-1)?.init.params?.query).toEqual({
        ...FIRST_PAGE,
        offset: 25,
        include_status_counts: false
      })
    );
  });

  it("counts on the first page only, and keeps those counts fresh while it polls", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const OLDER_PAGE = { ...FIRST_PAGE, offset: 25, include_status_counts: false };
    let failed = 1;
    state.routes[LIST] = (init: { params?: { query?: { offset?: number } } }) =>
      init.params?.query?.offset
        ? {
            body: {
              count: 1,
              items: [makeRunSummary({ id: "run-1", status: "failed" })],
              has_more: false,
              status_counts: null
            }
          }
        : {
            body: {
              count: 1,
              items: [makeRunSummary({ id: "run-2", status: "running", finished_at: null })],
              has_more: true,
              status_counts: { ...NO_COUNTS, running: 1, failed }
            }
          };
    renderInApp(<List />);
    fireEvent.click(await screen.findByRole("button", { name: messages.flow_runs_show_more }));
    await vi.waitFor(() => expect(listCalls()).toHaveLength(2));
    expect(listCalls()[1]?.init.params?.query).toEqual(OLDER_PAGE);

    failed = 2;
    await act(() => vi.advanceTimersByTimeAsync(2_100));
    await vi.waitFor(() => expect(listCalls()).toHaveLength(4));
    expect(
      listCalls()
        .slice(2)
        .map((call) => call.init.params?.query)
    ).toEqual([FIRST_PAGE, OLDER_PAGE]);
    fireEvent.click(screen.getByRole("combobox", { name: messages.flow_run_extras_status_filter }));
    expect(
      await screen.findByRole("option", { name: `${messages.flow_runs_status_failed} (2)` })
    ).toBeTruthy();
  });

  it("sends a queued run whose start is due again from its row", async () => {
    const queued = makeRunSummary({
      id: "run-q",
      status: "queued",
      started_at: null,
      finished_at: null,
      dispatch_next_attempt_at: "2026-10-21T08:00:05Z",
      dispatch_exhausted_at: null
    });
    answerList([queued, makeRunSummary({ id: "run-c" })]);
    state.routes[REDISPATCH] = () => ({ body: { redispatched_count: 1, run: queued } });
    const { container } = renderInApp(<List />);
    const table = await screen.findByRole("table");
    const buttons = within(table).getAllByRole("button", { name: messages.flow_runs_redispatch });
    // Only the queued run is offered it.
    expect(buttons).toHaveLength(1);
    await expectNoAxeViolations(container);

    fireEvent.click(buttons[0]!);

    await vi.waitFor(() =>
      expect(state.toast.success).toHaveBeenCalledWith(messages.flow_runs_redispatch_done)
    );
    const call = state.stub.calls.find((entry) => `${entry.method} ${entry.path}` === REDISPATCH);
    expect(call?.init.params?.path).toEqual({ id: "flow-1", run_id: "run-q" });
    await vi.waitFor(() => expect(listCalls().length).toBeGreaterThan(1));
  });

  it("retries a failed run from its row and opens the new run", async () => {
    answerList([makeRunSummary({ id: "run-f", status: "failed" }), makeRunSummary()]);
    state.routes[RETRY] = () => ({
      status: 201,
      body: {
        created: true,
        first_executed_step_order: 2,
        reused_step_orders: [1],
        source_run_id: "run-f",
        run: makeRunSummary({ id: "run-2", status: "queued" })
      }
    });
    const { container } = renderInApp(<List />, {
      appContext: testAppContext({ permissions: ["flows_view", "flows_run"] })
    });
    const table = await screen.findByRole("table");
    const buttons = within(table).getAllByRole("button", { name: messages.flow_runs_retry });
    expect(buttons).toHaveLength(1);
    await expectNoAxeViolations(container);

    fireEvent.click(buttons[0]!);

    await vi.waitFor(() =>
      expect(router.push).toHaveBeenCalledWith("/spaces/space-1/flows/flow-1/runs/run-2")
    );
    const call = state.stub.calls.find((entry) => `${entry.method} ${entry.path}` === RETRY);
    expect(call?.init.params?.path).toEqual({ id: "flow-1", run_id: "run-f" });
    expect(state.announce).toHaveBeenCalledWith(
      messages.flow_runs_retry_started.replace("{order}", "2")
    );
  });

  it("says in a toast that a retry was already started, with a way to it", async () => {
    answerList([makeRunSummary({ id: "run-f", status: "failed" })]);
    state.routes[RETRY] = () => ({
      body: {
        created: false,
        first_executed_step_order: 2,
        reused_step_orders: [1],
        source_run_id: "run-f",
        run: makeRunSummary({ id: "run-2" })
      }
    });
    renderInApp(<List />, {
      appContext: testAppContext({ permissions: ["flows_view", "flows_run"] })
    });
    fireEvent.click(await screen.findByRole("button", { name: messages.flow_runs_retry }));
    await vi.waitFor(() => expect(state.toast.info).toHaveBeenCalled());
    const [title, options] = state.toast.info.mock.calls[0] as [
      string,
      { action: { label: string; onClick: () => void } }
    ];
    expect(title).toBe(messages.flow_runs_retry_replayed);
    expect(options.action.label).toBe(messages.flow_runs_retry_replayed_open);
    expect(router.push).not.toHaveBeenCalled();
    options.action.onClick();
    expect(router.push).toHaveBeenCalledWith("/spaces/space-1/flows/flow-1/runs/run-2");
  });

  it("offers a retry by the run page's rules only", async () => {
    answerList([
      makeRunSummary({ id: "run-old", status: "failed", flow_version: 2 }),
      makeRunSummary({
        id: "run-other",
        status: "failed",
        started_by: { principal_type: "user", id: "user-2", display_name: "Erik Berg" }
      })
    ]);
    renderInApp(<List />, {
      appContext: testAppContext({ permissions: ["flows_view", "flows_run"] })
    });
    await screen.findByRole("table");
    // An older version cannot be retried, and only its starter retries a run.
    expect(screen.queryByRole("button", { name: messages.flow_runs_retry })).toBeNull();
    cleanup();

    answerList([makeRunSummary({ id: "run-f", status: "failed" })]);
    renderInApp(<List />, { appContext: testAppContext({ permissions: ["flows_view"] }) });
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: messages.flow_runs_retry })).toBeNull();
  });

  it("cancels a run under way from its row after asking, and keeps focus in the row", async () => {
    const running = makeRunSummary({
      id: "run-r",
      run_label: "Ärende 9",
      status: "running",
      finished_at: null
    });
    answerList([running, makeRunSummary()]);
    state.routes[CANCEL] = () => ({ body: { ...running, status: "cancelled" } });
    renderInApp(<List />);
    const table = await screen.findByRole("table");
    const cancel = within(table).getByRole("button", { name: messages.flow_runs_cancel });
    cancel.focus();
    fireEvent.click(cancel);
    const dialog = await screen.findByRole("alertdialog", {
      name: messages.flow_runs_cancel_title
    });
    expect(within(dialog).getByText(messages.flow_runs_cancel_description)).toBeTruthy();
    answerList([{ ...running, status: "cancelled" }, makeRunSummary()]);

    fireEvent.click(within(dialog).getByRole("button", { name: messages.flow_runs_cancel }));

    await vi.waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(messages.flow_runs_cancel_done)
    );
    await vi.waitFor(() =>
      expect(screen.queryByRole("button", { name: messages.flow_runs_cancel })).toBeNull()
    );
    await vi.waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("link", { name: "Ärende 9" }))
    );
    const call = state.stub.calls.find((entry) => `${entry.method} ${entry.path}` === CANCEL);
    expect(call?.init.params?.path).toEqual({ id: "flow-1", run_id: "run-r" });
  });

  it("says so in a toast when the run had already ended", async () => {
    const running = makeRunSummary({ id: "run-r", status: "running", finished_at: null });
    answerList([running]);
    state.routes[CANCEL] = () => ({ body: { ...running, status: "completed" } });
    renderInApp(<List />);
    fireEvent.click(await screen.findByRole("button", { name: messages.flow_runs_cancel }));
    const dialog = await screen.findByRole("alertdialog", {
      name: messages.flow_runs_cancel_title
    });
    fireEvent.click(within(dialog).getByRole("button", { name: messages.flow_runs_cancel }));
    await vi.waitFor(() =>
      expect(state.toast.info).toHaveBeenCalledWith(
        messages.flow_runs_cancel_already_ended.replace(
          "{status}",
          messages.flow_runs_status_completed
        ),
        undefined
      )
    );
  });

  it("does not offer it for a queued run whose start is not due yet", async () => {
    answerList([
      makeRunSummary({
        status: "queued",
        started_at: null,
        finished_at: null,
        dispatch_next_attempt_at: "2999-01-01T00:00:00Z"
      })
    ]);
    renderInApp(<List />);
    await screen.findByRole("table");
    expect(screen.queryByRole("button", { name: messages.flow_runs_redispatch })).toBeNull();
  });

  it("shows a run this tab just started before the list reports it, and then once", async () => {
    const queryClient = testQueryClient();
    rememberStartedRun(
      queryClient,
      "flow-1",
      makeRunDetail({ id: "run-new", status: "queued", run_label: "Ärende 7", started_at: null }),
      Date.now() + 60_000
    );
    answerList([makeRunSummary({ id: "run-1", status: "completed" })], false, {
      ...NO_COUNTS,
      completed: 1
    });
    renderInApp(<List />, { queryClient });
    expect(await screen.findByRole("link", { name: "Ärende 7" })).toBeTruthy();
    fireEvent.click(screen.getByRole("combobox", { name: messages.flow_run_extras_status_filter }));
    expect(
      await screen.findByRole("option", { name: `${messages.flow_runs_status_queued} (1)` })
    ).toBeTruthy();

    answerList([
      makeRunSummary({ id: "run-new", status: "queued", run_label: "Ärende 7", started_at: null }),
      makeRunSummary({ id: "run-1" })
    ]);
    await act(() => queryClient.invalidateQueries({ queryKey: ["flows", "flow-1", "runs"] }));
    await vi.waitFor(() => expect(listCalls().length).toBeGreaterThan(1));
    expect(screen.getAllByRole("link", { name: "Ärende 7" })).toHaveLength(1);
  });
});
