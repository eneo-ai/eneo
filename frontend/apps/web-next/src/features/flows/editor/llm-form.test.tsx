// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { flowFixture } from "../flow-fixtures";
import { FlowStepEditor } from "../flow-step-editor";
import type { FlowPublic, LlmStep } from "../types";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    routeId: "space-1",
    can: () => true,
    space: {
      id: "space-1",
      personal: false,
      completion_models: [
        {
          id: "model-1",
          name: "gpt",
          nickname: "GPT-5.2",
          supported_model_kwargs: {
            temperature: { supported: true, minimum: 0, maximum: 2, step: 0.1 },
            reasoning_effort: { supported: true, control: "select", options: ["low", "high"] }
          }
        }
      ],
      transcription_models: [],
      embedding_models: [],
      knowledge: {
        groups: { items: [{ id: "collection-1", name: "Delegationsordning" }] },
        websites: { items: [] },
        integration_knowledge_list: { items: [] }
      }
    }
  })
}));
vi.mock("@/features/knowledge/select/knowledge-picker", () => ({
  KnowledgePicker: ({ selections }: { selections: { collections: { name: string }[] } }) => (
    <div data-testid="knowledge">{selections.collections.map((c) => c.name).join(",")}</div>
  )
}));

const flow: FlowPublic = { ...flowFixture, editing: true, editors: [], step_origins: [] };
const summary = flow.definition.steps!.find((step) => step.key === "summary") as LlmStep;

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("LlmForm", () => {
  it("edits the prompt, model settings and the JSON schema, refusing an invalid schema", async () => {
    api.GET.mockResolvedValue({ data: { items: [] }, response: new Response("{}") });
    api.PATCH.mockResolvedValue({ data: { ...flow, revision: 5 }, response: new Response("{}") });
    renderInApp(
      <FlowStepEditor
        flow={flow}
        target={{ step: summary }}
        wide={false}
        onSaved={() => {}}
        onCancel={() => {}}
        onOpenRun={() => {}}
        onDeleted={() => {}}
      />
    );
    expect(screen.getByTestId("knowledge").textContent).toBe("Delegationsordning");
    expect(screen.getByLabelText("Inspelning")).toBeTruthy();
    expect(screen.getByLabelText("Temperatur")).toBeTruthy();
    expect(screen.getByLabelText(/Resonemang|Reasoning/i)).toBeTruthy();

    const schema = screen.getByLabelText(/JSON-schema/);
    fireEvent.change(schema, { target: { value: "{ broken" } });
    expect(screen.getByText("Texten är inte giltig JSON.")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "Spara som utkast" }));
    expect(api.PATCH).not.toHaveBeenCalled();

    fireEvent.change(schema, {
      target: { value: '{"type":"object","properties":{"decisions":{"type":"array"}}}' }
    });
    fireEvent.change(screen.getByLabelText(/Instruktion till modellen/), {
      target: { value: "Lista besluten, kort." }
    });
    fireEvent.click(screen.getByRole("button", { name: "Spara som utkast" }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    const sent = api.PATCH.mock.calls[0]![1].body.definition.steps[2] as LlmStep;
    expect(sent.prompt).toBe("Lista besluten, kort.");
    expect(sent.output).toEqual({
      type: "json",
      schema: { type: "object", properties: { decisions: { type: "array" } } }
    });
  });

  it("switches the output to text and drops the schema", () => {
    api.GET.mockResolvedValue({ data: { items: [] }, response: new Response("{}") });
    renderInApp(
      <FlowStepEditor
        flow={flow}
        target={{ step: summary }}
        wide={false}
        onSaved={() => {}}
        onCancel={() => {}}
        onOpenRun={() => {}}
        onDeleted={() => {}}
      />
    );
    fireEvent.click(screen.getByLabelText(/^Text/));
    expect(screen.queryByLabelText(/JSON-schema/)).toBeNull();
    expect(screen.getByText("1 fält ändrat i steg 3")).toBeTruthy();
  });
});
