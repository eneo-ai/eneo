// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { flowFixture } from "./flow-fixtures";
import { FlowRunDialog } from "./flow-run-dialog";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});
const flow = {
  ...flowFixture,
  has_unpublished_changes: false,
  definition: {
    schema_version: 1,
    steps: [],
    form_fields: [
      { key: "draft_only", label: "Endast i utkastet", type: "text" as const, required: true }
    ]
  }
};

it("runs published fields and the version from the published contract", async () => {
  api.GET.mockResolvedValue({
    data: {
      flow_id: flow.id,
      published_flow_version: 3,
      form_fields: [
        { key: "published_question", label: "Publicerad fråga", type: "text", required: true }
      ],
      steps_requiring_review: []
    },
    response: new Response("{}")
  });
  api.POST.mockResolvedValue({
    data: { id: "run-1", status: "queued" },
    response: new Response("{}")
  });
  const started = vi.fn();
  renderInApp(<FlowRunDialog flow={flow} open onOpenChange={() => {}} onStarted={started} />);
  const input = await screen.findByLabelText(/Publicerad fråga/);
  expect(screen.queryByLabelText(/Endast i utkastet/)).toBeNull();
  fireEvent.change(input, { target: { value: "Publicerad indata" } });
  await expectNoAxeViolations(screen.getByRole("dialog"));
  fireEvent.click(screen.getByRole("button", { name: "Starta körning" }));
  await waitFor(() => expect(started).toHaveBeenCalled());
  expect(api.POST).toHaveBeenCalledWith(
    "/api/v1/flows/{id}/runs/",
    expect.objectContaining({
      body: expect.objectContaining({
        values: { published_question: "Publicerad indata" },
        expected_flow_version: 3,
        draft: false
      })
    })
  );
});

it("does not start a published run before its contract loads", () => {
  api.GET.mockReturnValue(new Promise(() => {}));
  renderInApp(<FlowRunDialog flow={flow} open onOpenChange={() => {}} onStarted={() => {}} />);
  const button = screen.getByRole("button", { name: "Starta körning" });
  expect(button.getAttribute("disabled")).not.toBeNull();
  fireEvent.click(button);
  expect(api.POST).not.toHaveBeenCalled();
});

it("switches from draft fields to the published contract without submitting draft-only inputs", async () => {
  api.GET.mockResolvedValue({
    data: {
      flow_id: flow.id,
      published_flow_version: 3,
      form_fields: [
        { key: "published_question", label: "Publicerad fråga", type: "text", required: true }
      ],
      steps_requiring_review: []
    },
    response: new Response("{}")
  });
  api.POST.mockResolvedValue({
    data: { id: "run-2", status: "queued" },
    response: new Response("{}")
  });
  renderInApp(
    <FlowRunDialog
      flow={{ ...flow, has_unpublished_changes: true }}
      open
      onOpenChange={() => {}}
      onStarted={() => {}}
    />
  );
  fireEvent.change(screen.getByLabelText(/Endast i utkastet/), {
    target: { value: "Draft input" }
  });
  fireEvent.click(screen.getByRole("combobox", { name: "Kör" }));
  fireEvent.click(await screen.findByRole("option", { name: /Publicerad version/ }));
  fireEvent.change(await screen.findByLabelText(/Publicerad fråga/), {
    target: { value: "Published input" }
  });
  expect(screen.queryByLabelText(/Endast i utkastet/)).toBeNull();
  fireEvent.click(screen.getByRole("button", { name: "Starta körning" }));
  await waitFor(() => expect(api.POST).toHaveBeenCalledTimes(1));
  expect(api.POST.mock.calls[0]![1].body).toMatchObject({
    values: { published_question: "Published input" },
    expected_flow_version: 3,
    draft: false
  });
});
