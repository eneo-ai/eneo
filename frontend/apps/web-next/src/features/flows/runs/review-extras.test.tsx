// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { makeCheckpoint } from "./run-fixtures";
import type { ReviewCheckpoint } from "./runs-api";

const state = vi.hoisted(() => ({
  announce: vi.fn(),
  routes: {} as Record<string, (init: never) => { status?: number; body: unknown }>,
  stub: null as unknown as ReturnType<typeof import("../editor/testing/fixtures").apiStub>
}));

vi.mock("@/lib/api/browser", async () => {
  const { apiStub } = await import("../editor/testing/fixtures");
  state.stub = apiStub(new Proxy({}, { get: (_target, key: string) => state.routes[key] }));
  return { browserApi: state.stub.client };
});
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => state.announce
}));

import { ReviewPanel } from "./review-panel";

const CHECKPOINT = "/api/v1/flows/{id}/runs/{run_id}/review-checkpoints/{checkpoint_id}";
const APPROVE = `POST ${CHECKPOINT}/approve/`;
const EDIT = `PATCH ${CHECKPOINT}/`;
const EDITS = `GET ${CHECKPOINT}/edits`;
const NOW = Date.parse("2026-10-22T08:00:00Z");

function renderPanel(checkpoint: ReviewCheckpoint) {
  return renderInApp(
    <ReviewPanel checkpoint={checkpoint} mayReview now={NOW} onStale={() => undefined} />
  );
}

function calls(route: string) {
  return state.stub.calls.filter((item) => `${item.method} ${item.path}` === route);
}

function edit(revision: number, text: string, userId: string | null = "user-1") {
  return {
    id: `edit-${revision}`,
    checkpoint_id: "checkpoint-1",
    flow_id: "flow-1",
    flow_run_id: "run-1",
    tenant_id: "tenant-1",
    revision,
    cause: "reviewer_edit",
    payload_json: { text },
    payload_sha256_before: "a",
    payload_sha256_after: "b",
    corrections_revision_id: null,
    edited_by_principal_type: "user",
    edited_by_user_id: userId,
    edited_by_service_id: null,
    created_at: "2026-10-21T09:00:00Z"
  };
}

beforeEach(() => {
  state.routes = {};
});

afterEach(() => {
  cleanup();
  state.stub.calls.length = 0;
  vi.clearAllMocks();
});

describe("ReviewPanel extras", () => {
  it("shows the sources the paused answer cited, and says when an edit left them behind", async () => {
    const { container } = renderPanel(
      makeCheckpoint({
        citation_summary: {
          status: "observed",
          matched_cited_source_count: 1,
          sources: [
            { display_name: "Bygglovspolicy", container_label: "Policys", identity_resolved: true }
          ],
          sources_truncated: false,
          stale_after_edit: true
        }
      })
    );
    expect(screen.getByText(messages.flow_run_extras_review_citations)).toBeTruthy();
    expect(screen.getByText("Bygglovspolicy · Policys")).toBeTruthy();
    expect(screen.getByText(messages.flow_runs_citations_stale)).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("approves without continuing the run, for the saved output only", async () => {
    state.routes[APPROVE] = () => ({ body: makeCheckpoint({ state: "approved", revision: 2 }) });
    renderPanel(makeCheckpoint());

    fireEvent.click(
      screen.getByRole("button", { name: messages.flow_run_extras_review_approve_only })
    );
    await vi.waitFor(() => expect(calls(APPROVE)).toHaveLength(1));
    expect(calls(APPROVE)[0]?.init.body).toEqual({ expected_checkpoint_revision: 1 });
    await vi.waitFor(() =>
      expect(state.announce).toHaveBeenCalledWith(messages.flow_run_extras_review_approved_only)
    );

    fireEvent.change(screen.getByLabelText(/^Stegets text/), { target: { value: "Ändrad" } });
    expect(
      screen.queryByRole("button", { name: messages.flow_run_extras_review_approve_only })
    ).toBeNull();
  });

  it("reads the edit history when opened, page by page, with each change before and after", async () => {
    state.routes[EDITS] = (init: { params?: { query?: Record<string, unknown> } }) =>
      init.params?.query?.after_revision === undefined
        ? {
            body: {
              baseline: { revision: 1, payload_sha256: "a", payload_json: { text: "Första" } },
              items: [edit(2, "Andra")],
              truncated: true,
              next_after_revision: 2
            }
          }
        : {
            body: {
              baseline: { revision: 2, payload_sha256: "b", payload_json: { text: "Andra" } },
              items: [edit(3, "Tredje", "user-2")],
              truncated: false,
              next_after_revision: null
            }
          };
    const { container } = renderPanel(makeCheckpoint({ revision: 3, state: "edited" }));
    expect(calls(EDITS)).toHaveLength(0);

    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_extras_history_heading }));
    const list = await screen.findByRole("list", {
      name: messages.flow_run_extras_history_heading
    });
    expect(calls(EDITS)[0]?.init.params?.query).toEqual({ limit: 20 });
    fireEvent.click(within(list).getByRole("button", { name: /Version 2/ }));
    expect(within(list).getByText(messages.flow_run_extras_history_original)).toBeTruthy();
    expect(within(list).getByText("Första")).toBeTruthy();
    expect(within(list).getByText("Andra")).toBeTruthy();
    expect(
      within(list).getByText(new RegExp(messages.flow_run_extras_history_by_you))
    ).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_extras_history_more }));
    expect(await within(list).findByRole("button", { name: /Version 3/ })).toBeTruthy();
    expect(calls(EDITS)[1]?.init.params?.query).toEqual({ limit: 20, after_revision: 2 });
    expect(
      within(list).getByText(new RegExp(messages.flow_run_extras_history_by_other))
    ).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("marks the flat fields a review changed, and shows the step's own output", async () => {
    const { container } = renderPanel(
      makeCheckpoint({
        output_type: "json",
        revision: 2,
        state: "edited",
        current_payload_json: { structured: { mottagare: "Bo", antal: 2 } },
        original_payload_json: { structured: { mottagare: "Anna", antal: 2 } }
      })
    );
    expect(screen.getAllByText(messages.flow_run_review_changed)).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_review_previous_value }));
    expect(screen.getByText("Anna")).toBeTruthy();
    await expectNoAxeViolations(container);

    fireEvent.change(screen.getByLabelText(/^antal/), { target: { value: "3" } });
    expect(screen.getAllByText(messages.flow_run_review_changed)).toHaveLength(2);

    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_review_show_original }));
    expect(screen.getByText(messages.flow_run_review_original_help)).toBeTruthy();
    expect(screen.queryByLabelText(/^mottagare/)).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_review_back_to_edit }));
    expect((screen.getByLabelText(/^antal/) as HTMLInputElement).value).toBe("3");
  });

  it("edits nested JSON as a form built from the output contract", async () => {
    state.routes[EDIT] = () => ({ body: makeCheckpoint({ revision: 2, state: "edited" }) });
    const contract = {
      type: "object",
      properties: {
        sammanfattning: { type: "string", title: "Sammanfattning" },
        punkter: {
          type: "array",
          title: "Punkter",
          items: {
            type: "object",
            required: ["text"],
            properties: { text: { type: "string", title: "Text" } }
          }
        }
      }
    };
    const { container } = renderPanel(
      makeCheckpoint({
        output_type: "json",
        output_contract: contract,
        current_payload_json: {
          structured: { sammanfattning: "Kort", punkter: [{ text: "Ring Anna" }] }
        }
      })
    );

    fireEvent.change(screen.getByLabelText(/^Sammanfattning/), {
      target: { value: "Kort och tydlig" }
    });
    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_extras_review_add_row }));
    const added = screen.getAllByLabelText(/^Text/).at(-1)!;
    expect(document.activeElement).toBe(added);
    fireEvent.change(added, { target: { value: "Skicka beslut" } });
    fireEvent.click(screen.getByRole("button", { name: "Ta bort rad 1" }));
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: messages.flow_run_extras_review_add_row })
    );
    await expectNoAxeViolations(container);

    fireEvent.click(screen.getByRole("button", { name: messages.flow_runs_review_save }));
    await vi.waitFor(() => expect(calls(EDIT)).toHaveLength(1));
    expect(calls(EDIT)[0]?.init.body).toEqual({
      edited_value: { sammanfattning: "Kort och tydlig", punkter: [{ text: "Skicka beslut" }] },
      expected_checkpoint_revision: 1
    });
  });
});
