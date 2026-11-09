// @vitest-environment jsdom
import { act, cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, onTestFinished, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { router } from "@/test/navigation";
import { renderInApp, testAppContext, testQueryClient } from "@/test/render";
import { reportResize, setViewport } from "@/test/setup-dom";
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

import { FlowRunsList, RUNS_TABLE_WIDTH } from "./runs-list";
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

/** The given runs and enough others that the filters show above them (more than three). */
function withOthers(...runs: RunListItem[]): RunListItem[] {
  return [...runs, ...["other-1", "other-2", "other-3"].map((id) => makeRunSummary({ id }))];
}

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

  it("says on a phone where to publish a flow that has no runs, not that runs will show", async () => {
    setViewport("phone");
    answerList([]);
    renderInApp(<FlowRunsList flowId="flow-1" spaceRouteId="space-1" publishedVersion={null} />);
    expect(
      await screen.findByText(messages.flow_runs_empty_description_unpublished_phone)
    ).toBeTruthy();
    expect(screen.queryByText(messages.flow_runs_empty_description)).toBeNull();
  });

  it("asks for the caller's own runs only when asked", async () => {
    answerList(withOthers(makeRunSummary()));
    renderInApp(<List />);
    await screen.findByRole("table");
    expect(listCalls()[0]?.init.params?.query).toEqual(FIRST_PAGE);

    fireEvent.click(screen.getByRole("checkbox", { name: messages.flow_runs_only_mine }));
    await vi.waitFor(() =>
      expect(listCalls().at(-1)?.init.params?.query).toEqual({ ...FIRST_PAGE, mine: true })
    );
  });

  it("asks the list endpoint for one status and says when none has it", async () => {
    answerList(withOthers(makeRunSummary()));
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
    answerList(withOthers(makeRunSummary()));
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
    answerList(withOthers(makeRunSummary({ status: "failed" })), false, {
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

  it("offers the review of a run waiting for one, and says how long it has waited", async () => {
    answerList([
      makeRunSummary({
        id: "run-r",
        status: "awaiting_review",
        started_at: new Date(Date.now() - 600_000).toISOString(),
        updated_at: new Date(Date.now() - 125_000).toISOString(),
        finished_at: null
      })
    ]);
    const { container } = renderInApp(<List />);
    const table = await screen.findByRole("table");
    const [, row] = within(table).getAllByRole("row");
    const review = within(row!).getByRole("link", { name: messages.flow_runs_review_open });
    expect(review.getAttribute("href")).toBe("/spaces/space-1/flows/flow-1/runs/run-r");
    // Cancelling stays quiet beside the review it would throw away.
    const cancel = within(row!).getByRole("button", { name: messages.flow_runs_cancel });
    expect(cancel.getAttribute("data-variant")).toBe("ghost");
    // The person's wait since the run paused, not a clock of the run working since it started.
    const waited = messages.flow_runs_waited.replace("{time}", "");
    expect(within(row!).getByText(new RegExp(`^${waited}2 min [56] s$`))).toBeTruthy();
    expect(row!.textContent).not.toContain(messages.flow_run_more_elapsed.replace("{time}", ""));
    await expectNoAxeViolations(container);
  });

  it("leaves out the filters while there is little to filter, on every screen", async () => {
    answerList([makeRunSummary({ id: "run-1" }), makeRunSummary({ id: "run-2" })]);
    renderInApp(<List />);
    await screen.findByRole("table");
    expect(screen.queryByRole("textbox", { name: messages.flow_run_journey_search })).toBeNull();
    expect(
      screen.queryByRole("combobox", { name: messages.flow_run_extras_status_filter })
    ).toBeNull();
    expect(screen.queryByRole("checkbox", { name: messages.flow_runs_only_mine })).toBeNull();
  });

  it("stops polling a list the person may no longer read", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    answerList([makeRunSummary({ status: "running", finished_at: null })]);
    renderInApp(<List />);
    await screen.findByRole("table");

    state.routes[LIST] = () => ({ status: 403, body: { message: "Forbidden" } });
    await act(() => vi.advanceTimersByTimeAsync(2_100));
    expect(listCalls()).toHaveLength(2);
    await act(() => vi.advanceTimersByTimeAsync(60_000));
    expect(listCalls()).toHaveLength(2);
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

  it("keeps the runs on screen when a poll fails, and says so", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    answerList([makeRunSummary({ status: "running", finished_at: null })]);
    renderInApp(<List />);
    const table = await screen.findByRole("table");

    state.routes[LIST] = () => ({ status: 503, body: { message: "Busy" } });
    await act(() => vi.advanceTimersByTimeAsync(2_100));

    expect(await screen.findByText(messages.query_error_refresh_title)).toBeTruthy();
    expect(within(table).getByText(messages.flow_runs_status_running)).toBeTruthy();
    expect(screen.queryByText(messages.flow_runs_list_failed)).toBeNull();
  });

  it("keeps the runs read so far when an older page fails, and retries that page", async () => {
    const first = {
      count: 1,
      items: [makeRunSummary()],
      has_more: true,
      status_counts: NO_COUNTS
    };
    let older: { status?: number; body: unknown } = { status: 503, body: { message: "Busy" } };
    state.routes[LIST] = (init: { params: { query: { offset: number } } }) =>
      init.params.query.offset === 0 ? { body: first } : older;
    renderInApp(<List />);
    const table = await screen.findByRole("table");
    fireEvent.click(screen.getByRole("button", { name: messages.flow_runs_show_more }));

    expect(await screen.findByText(messages.query_error_load_more_title)).toBeTruthy();
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(screen.queryByText(messages.flow_runs_list_failed)).toBeNull();

    older = {
      body: {
        count: 1,
        items: [makeRunSummary({ id: "run-0" })],
        has_more: false,
        status_counts: null
      }
    };
    fireEvent.click(
      screen.getByRole("button", {
        name: messages.query_error_retry_named.replace(
          "{section}",
          messages.query_error_load_more_title
        )
      })
    );
    await vi.waitFor(() => expect(within(table).getAllByRole("row")).toHaveLength(3));
    expect(listCalls()).toHaveLength(3);
    expect(listCalls()[2]?.init.params?.query).toEqual({
      ...FIRST_PAGE,
      offset: 25,
      include_status_counts: false
    });
    expect(screen.queryByText(messages.query_error_load_more_title)).toBeNull();
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
              items: withOthers(
                makeRunSummary({ id: "run-2", status: "running", finished_at: null })
              ),
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

  it("says why a row's action failed, with the error id to quote to support", async () => {
    const unexpected = { message: "An unexpected error occurred.", error_id: "err-1" };
    const queued = makeRunSummary({
      id: "run-q",
      status: "queued",
      started_at: null,
      finished_at: null,
      dispatch_next_attempt_at: "2026-10-21T08:00:05Z",
      dispatch_exhausted_at: null
    });
    answerList([queued]);
    state.routes[REDISPATCH] = () => ({ status: 500, body: unexpected });
    state.routes[CANCEL] = () => ({ status: 500, body: unexpected });
    renderInApp(<List />);
    const table = await screen.findByRole("table");
    const description = `${messages.error_occurred} · ${messages.error_id}: err-1`;

    fireEvent.click(within(table).getByRole("button", { name: messages.flow_runs_redispatch }));
    await vi.waitFor(() =>
      expect(state.toast.error).toHaveBeenCalledWith(messages.flow_runs_redispatch_failed, {
        description
      })
    );

    fireEvent.click(within(table).getByRole("button", { name: messages.flow_runs_cancel }));
    const dialog = await screen.findByRole("alertdialog", {
      name: messages.flow_runs_cancel_title
    });
    fireEvent.click(within(dialog).getByRole("button", { name: messages.flow_runs_cancel }));
    await vi.waitFor(() =>
      expect(state.toast.error).toHaveBeenCalledWith(messages.flow_runs_cancel_failed, {
        description
      })
    );
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
    answerList(withOthers(makeRunSummary({ id: "run-1", status: "completed" })), false, {
      ...NO_COUNTS,
      completed: 4
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

describe("FlowRunsList on a phone", () => {
  const withRun = () =>
    renderInApp(<List />, {
      appContext: testAppContext({ permissions: ["flows_view", "flows_run"] })
    });

  it("lists the runs as rows with their state, who started them and how long, and the retry of a failed one", async () => {
    setViewport("phone");
    answerList([
      makeRunSummary({ id: "run-f", status: "failed" }),
      {
        ...makeRunSummary({ id: "run-ok" }),
        token_usage: {
          num_tokens_input: 1000,
          num_tokens_output: 200,
          num_tokens_total: 1200,
          input_completeness: "complete",
          output_completeness: "complete"
        }
      }
    ]);
    const { container } = withRun();

    const list = await screen.findByRole("list", { name: messages.flow_runs_heading });
    expect(screen.queryByRole("table")).toBeNull();
    const rows = within(list).getAllByRole("listitem");
    expect(rows).toHaveLength(2);
    expect(within(rows[0]!).getByText(messages.flow_runs_status_failed)).toBeTruthy();
    expect(within(rows[0]!).getByText("Anna Lind · 1 min 5 s")).toBeTruthy();
    expect(within(rows[0]!).getByRole("link", { name: /./ }).getAttribute("href")).toBe(
      "/spaces/space-1/flows/flow-1/runs/run-f"
    );
    expect(within(rows[0]!).getByRole("button", { name: messages.flow_runs_retry })).toBeTruthy();
    expect(within(rows[1]!).queryByRole("button", { name: messages.flow_runs_retry })).toBeNull();
    // What only a wide screen has room for.
    expect(screen.queryByText(messages.flow_runs_usage_tokens_explainer)).toBeNull();
    await expectNoAxeViolations(container);
  });

  it("says only who started a run with no time to report, not a bare dash after a dot", async () => {
    setViewport("phone");
    // Not running and never finished: there is no duration to give.
    answerList([makeRunSummary({ id: "run-x", status: "failed", finished_at: null })]);
    withRun();
    const list = await screen.findByRole("list", { name: messages.flow_runs_heading });
    const row = within(list).getByRole("listitem");
    expect(within(row).getByText("Anna Lind")).toBeTruthy();
    expect(row.textContent).not.toContain("–");
  });

  const fourRuns = () => ["run-1", "run-2", "run-3", "run-4"].map((id) => makeRunSummary({ id }));

  it("leaves out the filters while there is little to filter, and keeps them for a search that finds nothing", async () => {
    setViewport("phone");
    answerList([]);
    withRun();
    expect(await screen.findByText(messages.flow_runs_empty_title)).toBeTruthy();
    expect(screen.queryByRole("textbox", { name: /Sök körningar/ })).toBeNull();
    expect(screen.queryByRole("checkbox", { name: messages.flow_runs_only_mine })).toBeNull();
    cleanup();

    // Three runs fit on the screen by themselves.
    answerList(fourRuns().slice(0, 3));
    withRun();
    await screen.findByRole("list", { name: messages.flow_runs_heading });
    expect(screen.queryByRole("textbox", { name: /Sök körningar/ })).toBeNull();
    cleanup();

    answerList(fourRuns());
    withRun();
    const search = await screen.findByRole("textbox", { name: /Sök körningar/ });
    // Searching for something that is not there leaves an empty list: the field stays.
    answerList([]);
    fireEvent.change(search, { target: { value: "finns inte" } });
    await screen.findByText(/finns inte/);
    expect(screen.getByRole("textbox", { name: /Sök körningar/ })).toBe(search);
  });

  it("keeps the search field while the whole list comes back after a cleared search", async () => {
    setViewport("phone");
    answerList(fourRuns());
    const { queryClient } = withRun();
    const search = await screen.findByRole("textbox", { name: /Sök körningar/ });
    answerList(fourRuns().slice(0, 1));
    fireEvent.change(search, { target: { value: "ett" } });
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(1));
    // The whole list has left the cache by the time the search is cleared.
    queryClient.removeQueries({ predicate: (query) => !query.isActive() });

    // The one row stays until the answer is in, and so must the field the person is in.
    let release!: () => void;
    const held = new Promise<void>((resolve) => {
      release = resolve;
    });
    const get = state.stub.client.GET;
    const spy = vi.spyOn(state.stub.client, "GET").mockImplementation((path, init) => {
      const answer = get(path, init);
      return `GET ${path}` === LIST ? held.then(() => answer) : answer;
    });
    onTestFinished(() => spy.mockRestore());
    answerList(fourRuns());
    fireEvent.change(search, { target: { value: "" } });
    await waitFor(() => expect(spy).toHaveBeenCalled());
    expect(screen.getByRole("textbox", { name: /Sök körningar/ })).toBe(search);
    release();
    await waitFor(() => expect(screen.getAllByRole("listitem")).toHaveLength(4));
    expect(screen.getByRole("textbox", { name: /Sök körningar/ })).toBe(search);
  });

  it("gives the search field the whole width, without its hint", async () => {
    setViewport("phone");
    answerList(fourRuns());
    withRun();
    const search = await screen.findByRole("textbox", { name: /Sök körningar/ });
    expect(screen.queryByText(messages.flow_run_journey_search_hint)).toBeNull();
    expect(search.closest(".astryx-field")?.getAttribute("style")).toContain("100%");
  });

  it("keeps the table on a tablet", async () => {
    setViewport("tablet-portrait");
    answerList([makeRunSummary({ id: "run-f", status: "failed" })]);
    withRun();
    expect(await screen.findByRole("table", { name: messages.flow_runs_heading })).toBeTruthy();
  });
});

describe("FlowRunsList in a narrow panel", () => {
  const measured = () => {
    const list = renderInApp(<List />, {
      appContext: testAppContext({ permissions: ["flows_view", "flows_run"] })
    });
    return list.container.querySelector("section")!;
  };
  const withUsage = () => {
    answerList([
      {
        ...makeRunSummary({ id: "run-1" }),
        token_usage: {
          num_tokens_input: 1000,
          num_tokens_output: 200,
          num_tokens_total: 1200,
          input_completeness: "complete",
          output_completeness: "complete"
        }
      }
    ]);
  };

  it("stacks the rows by the room it has, not the window's, with no column's footnote", async () => {
    withUsage();
    const section = measured();
    expect(await screen.findByRole("table", { name: messages.flow_runs_heading })).toBeTruthy();
    // What a token is stays folded away until asked for.
    const explainer = screen.getByRole("button", {
      name: messages.flow_runs_usage_tokens_explainer_title
    });
    expect(explainer.getAttribute("aria-expanded")).toBe("false");
    fireEvent.click(explainer);
    expect(explainer.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText(messages.flow_runs_usage_tokens_explainer)).toBeTruthy();

    act(() => reportResize(section, { width: 560 }));
    expect(screen.queryByRole("table")).toBeNull();
    const list = screen.getByRole("list", { name: messages.flow_runs_heading });
    const [row] = within(list).getAllByRole("listitem");
    expect(within(row!).getByText("Anna Lind · 1 min 5 s · Version 3")).toBeTruthy();
    expect(within(row!).getByText(/^1\s200 token$/)).toBeTruthy();
    expect(screen.queryByText(messages.flow_runs_usage_tokens_explainer)).toBeNull();
  });

  it("stacks from the first paint in a narrow panel, before the observer answers", async () => {
    const rect = vi.spyOn(HTMLElement.prototype, "getBoundingClientRect");
    onTestFinished(() => rect.mockRestore());
    rect.mockImplementation(function (this: HTMLElement) {
      const width = this.tagName === "SECTION" ? 560 : 0;
      return { x: 0, y: 0, top: 0, left: 0, width, height: 0, right: width, bottom: 0 } as DOMRect;
    });
    withUsage();
    measured();
    expect(await screen.findByRole("list", { name: messages.flow_runs_heading })).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });

  it("keeps the table where all its columns fit, and asks for no more room than it stacks at", async () => {
    withUsage();
    const section = measured();
    const table = await screen.findByRole("table", { name: messages.flow_runs_heading });
    expect(Number.parseFloat(table.style.minWidth)).toBeLessThanOrEqual(RUNS_TABLE_WIDTH);

    act(() => reportResize(section, { width: RUNS_TABLE_WIDTH }));
    expect(screen.getByRole("table", { name: messages.flow_runs_heading })).toBeTruthy();
    act(() => reportResize(section, { width: RUNS_TABLE_WIDTH - 1 }));
    expect(screen.queryByRole("table")).toBeNull();
  });
});
