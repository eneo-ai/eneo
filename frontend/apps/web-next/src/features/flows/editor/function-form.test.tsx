// @vitest-environment jsdom
import { cleanup, fireEvent, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { flowFixture, functionsFixture } from "../flow-fixtures";
import { FlowStepEditor } from "../flow-step-editor";
import type { FlowPublic, FunctionStep } from "../types";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

const flow: FlowPublic = { ...flowFixture, editing: true, editors: [], step_origins: [] };
const chart = flow.definition.steps!.find((step) => step.key === "chart") as FunctionStep;

function editor(step: FunctionStep) {
  api.GET.mockResolvedValue({ data: { items: [] }, response: new Response("{}") });
  renderInApp(
    <FlowStepEditor
      flow={flow}
      target={{ step }}
      functions={functionsFixture}
      wide={false}
      onSaved={() => {}}
      onCancel={() => {}}
      onOpenRun={() => {}}
      onDeleted={() => {}}
    />
  );
}

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FunctionForm", () => {
  it("offers the provider's tools by name and names the tool's arguments", () => {
    editor(chart);
    const tool = screen.getByRole("combobox", { name: /Verktyg/ });
    expect(tool.textContent).toContain("render_chart");
    expect(screen.getByText("Verktygets argument: data*, kind (* krävs).")).toBeTruthy();
    expect(screen.getAllByText("Diagramtjänsten").length).toBeGreaterThan(0);
    expect(screen.queryByText(/Steget kan inte köras/)).toBeNull();
  });

  it("says why a purpose cannot run and falls back to a typed tool name", () => {
    editor({ ...chart, purpose: "compute", tool: "run_python", arguments: {} });
    expect(screen.getAllByText("Ingen leverantör i rummet").length).toBeGreaterThan(0);
    const tool = screen.getByLabelText(/Verktyg/) as HTMLInputElement;
    expect(tool.value).toBe("run_python");
    expect(
      screen.getByText(/Ingen leverantör nås just nu, så verktygen kan inte listas/)
    ).toBeTruthy();
  });

  it("flags a tool the provider does not offer", () => {
    editor({ ...chart, tool: "draw" });
    expect(screen.getByText("Finns inte hos leverantören")).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/^Namn/), { target: { value: "Rita" } });
    expect(screen.getByText("1 fält ändrat i steg 6")).toBeTruthy();
  });
});
