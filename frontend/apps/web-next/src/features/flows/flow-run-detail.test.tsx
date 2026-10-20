// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { FlowRunDetail } from "./flow-run-detail";
import type { FlowDefinition, FlowRunPublic } from "./types";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn() }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

const definition: FlowDefinition = {
  schema_version: 1,
  form_fields: [
    { key: "topic", label: "Ämne", type: "text", required: true },
    { key: "attachment", label: "Underlag", type: "file", required: false }
  ],
  steps: [
    { kind: "llm", key: "draft", id: "s1", name: "Utkast", prompt: "Skriv om {{form.topic}}" },
    { kind: "review", key: "check", id: "s2", name: "Granska", mode: "edit", of: "draft" },
    { kind: "document", key: "doc", id: "s3", name: "Rapport", format: "docx", content: "x" }
  ]
};

type RunStep = NonNullable<FlowRunPublic["steps"]>[number];

const base = {
  id: "run-1",
  flow_id: "flow-1",
  flow_version: 2,
  tenant_id: "tenant-1",
  principal_type: "user" as const,
  run_label: "Oktober",
  job_id: null,
  started_at: "2026-10-20T09:00:00Z",
  finished_at: null,
  cancelled_at: null,
  created_at: "2026-10-20T09:00:00Z",
  updated_at: "2026-10-20T09:00:10Z",
  input_payload_json: { topic: "hamnar" },
  output_payload_json: null,
  error: null,
  input_files: [
    { id: "file-in", name: "underlag.pdf", mimetype: "application/pdf", role: "input" as const }
  ],
  review_checkpoint: null
};

const step = (index: number, status: RunStep["status"], extra: Partial<RunStep> = {}): RunStep => {
  const source = definition.steps![index]!;
  return {
    step_id: source.id!,
    key: source.key,
    name: source.name,
    kind: source.kind,
    step_order: index,
    status,
    current_attempt_no: status === "pending" ? 0 : 1,
    ...extra
  };
};

const pausedRun: FlowRunPublic = {
  ...base,
  status: "awaiting_review",
  result_files: [],
  steps: [
    step(0, "completed", {
      input_payload_json: { text: "hamnar" },
      output_payload_json: { text: "Hamnar är **viktiga**.", value: null },
      num_tokens_output: 12,
      started_at: "2026-10-20T09:00:00Z",
      finished_at: "2026-10-20T09:00:04Z"
    }),
    step(1, "awaiting_review"),
    step(2, "pending")
  ],
  review_checkpoint: {
    id: "cp-1",
    flow_id: "flow-1",
    flow_run_id: "run-1",
    step_id: "s2",
    step_order: 1,
    attempt_no: 1,
    state: "awaiting_review",
    revision: 1,
    review_mode: "edit",
    output_type: "text",
    original_payload_json: { text: "Hamnar är **viktiga**.", value: null },
    current_payload_json: { text: "Hamnar är **viktiga**.", value: null },
    requester_principal_type: "user",
    created_at: "2026-10-20T09:00:04Z",
    updated_at: "2026-10-20T09:00:04Z"
  }
};

const finishedRun: FlowRunPublic = {
  ...base,
  status: "completed",
  finished_at: "2026-10-20T09:01:00Z",
  output_payload_json: { text: "Rapport.docx", value: null, file_ids: ["file-out"] },
  result_files: [
    {
      id: "file-out",
      name: "Rapport.docx",
      mimetype: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
      role: "output",
      step_id: "s3"
    }
  ],
  steps: [
    step(0, "completed", { output_payload_json: { text: "Hamnar är viktiga.", value: null } }),
    step(1, "completed", { output_payload_json: { text: "Hamnar är viktiga.", value: null } }),
    step(2, "completed", {
      output_payload_json: { text: "Rapport.docx", value: null, file_ids: ["file-out"] },
      result_files: [
        {
          id: "file-out",
          name: "Rapport.docx",
          mimetype: "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
          role: "output",
          step_id: "s3"
        }
      ]
    })
  ]
};

function mockRun(run: FlowRunPublic) {
  api.GET.mockImplementation((path: string) => {
    if (path === "/api/v1/flows/{id}/runs/{run_id}/")
      return Promise.resolve({ data: run, response: new Response("{}") });
    return Promise.reject(new Error(`unexpected GET ${path}`));
  });
}

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("FlowRunDetail", () => {
  it("shows a paused run with its inputs, step outputs and the review decision", async () => {
    mockRun(pausedRun);
    const { container } = renderInApp(
      <FlowRunDetail flowId="flow-1" runId="run-1" definition={definition} onBack={() => {}} />
    );

    expect(await screen.findByRole("heading", { level: 3, name: "Körning Oktober" })).toBeTruthy();
    expect(screen.getByText("Väntar på granskning")).toBeTruthy();
    // The decision comes first, named after the step that waits.
    const outcome = screen.getByRole("region", { name: "Väntar på granskning: Granska" });
    expect(within(outcome).getByRole("button", { name: "Godkänn" })).toBeTruthy();
    expect(within(outcome).getByRole("button", { name: "Spara och godkänn" })).toBeTruthy();
    expect(within(outcome).getByRole("button", { name: "Avvisa" })).toBeTruthy();
    // Inputs stay in view: the values as chips, the uploaded file as a chip.
    const inputs = screen.getAllByText("Indata")[0]!.closest("details")!;
    expect(inputs.hasAttribute("open")).toBe(true);
    expect(within(inputs).getByText("Ämne: hamnar")).toBeTruthy();
    const inputFiles = within(inputs).getByRole("list", { name: "Indatafiler" });
    expect(within(inputFiles).getByRole("button", { name: /underlag\.pdf/ })).toBeTruthy();
    // Every step in order with its state; payloads stay closed with a preview.
    const steps = container.querySelector("ol")!;
    const items = within(steps).getAllByRole("listitem");
    expect(items.map((item) => item.textContent)).toEqual([
      expect.stringContaining("1 · Utkast"),
      expect.stringContaining("2 · Granska"),
      expect.stringContaining("3 · Rapport")
    ]);
    const output = within(items[0]!).getByText("Utdata").closest("details")!;
    expect(output.hasAttribute("open")).toBe(false);
    expect(output.textContent).toContain("Hamnar är **viktiga**.");
    expect(within(items[0]!).getByText(/12 tokens/)).toBeTruthy();
    expect(within(items[1]!).queryByRole("button", { name: "Godkänn" })).toBeNull();
    // An active run can be cancelled.
    expect(screen.getByRole("button", { name: "Avbryt körning" })).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("offers a finished run's document as a file and no cancel", async () => {
    mockRun(finishedRun);
    renderInApp(
      <FlowRunDetail flowId="flow-1" runId="run-1" definition={definition} onBack={() => {}} />
    );

    expect(await screen.findByText("Klar")).toBeTruthy();
    const outcome = screen.getByRole("region", { name: "Flödet är klart" });
    expect(within(outcome).getByText(/3 steg kördes/)).toBeTruthy();
    const results = within(outcome).getByRole("list", { name: "Skapade filer" });
    expect(within(results).getByRole("button", { name: /Rapport\.docx/ })).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Avbryt körning" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Godkänn" })).toBeNull();
  });

  it("cancels through the run's cancel endpoint", async () => {
    mockRun(pausedRun);
    api.POST.mockResolvedValue({
      data: { ...pausedRun, status: "cancelled" },
      response: new Response("{}")
    });
    renderInApp(
      <FlowRunDetail flowId="flow-1" runId="run-1" definition={definition} onBack={() => {}} />
    );

    fireEvent.click(await screen.findByRole("button", { name: "Avbryt körning" }));
    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith(
        "/api/v1/flows/{id}/runs/{run_id}/cancel/",
        expect.objectContaining({ params: { path: { id: "flow-1", run_id: "run-1" } } })
      )
    );
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("goes back to the list", async () => {
    mockRun(finishedRun);
    const onBack = vi.fn();
    renderInApp(
      <FlowRunDetail flowId="flow-1" runId="run-1" definition={definition} onBack={onBack} />
    );
    fireEvent.click(await screen.findByRole("button", { name: "Tillbaka till körningarna" }));
    expect(onBack).toHaveBeenCalledTimes(1);
  });
});
