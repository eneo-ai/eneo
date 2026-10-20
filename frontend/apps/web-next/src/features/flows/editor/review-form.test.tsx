// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { flowFixture } from "../flow-fixtures";
import { FlowStepEditor } from "../flow-step-editor";
import type { FlowPublic, ReviewStep } from "../types";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

const flow: FlowPublic = { ...flowFixture, editing: true, editors: [], step_origins: [] };
const check = flow.definition.steps!.find((step) => step.key === "check") as ReviewStep;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("ReviewForm", () => {
  it("edits the mode, the reviewed step and the time limit in days, hours or minutes", async () => {
    api.GET.mockResolvedValue({ data: { items: [] }, response: new Response("{}") });
    api.PATCH.mockResolvedValue({ data: { ...flow, revision: 5 }, response: new Response("{}") });
    renderInApp(
      <FlowStepEditor
        flow={flow}
        target={{ step: check }}
        wide={false}
        onSaved={() => {}}
        onCancel={() => {}}
        onOpenRun={() => {}}
        onDeleted={() => {}}
      />
    );
    expect((screen.getByLabelText("Tidsgräns") as HTMLInputElement).value).toBe("7");
    fireEvent.click(screen.getByLabelText(/Endast godkänna eller avvisa/));
    fireEvent.change(screen.getByLabelText("Tidsgräns"), { target: { value: "36" } });
    fireEvent.blur(screen.getByLabelText("Tidsgräns"));
    expect(screen.getByText("2 fält ändrade i steg 2")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Spara som utkast" }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    const sent = api.PATCH.mock.calls[0]![1].body.definition.steps[1];
    expect(sent).toMatchObject({
      kind: "review",
      mode: "view",
      expires_after_seconds: 36 * 86_400
    });
  });
});
