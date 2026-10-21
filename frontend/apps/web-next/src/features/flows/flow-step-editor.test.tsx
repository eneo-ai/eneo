// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { renderInApp } from "@/test/render";
import { flowFixture, namesFixture as names } from "./flow-fixtures";
import { FlowStepEditor } from "./flow-step-editor";
import type { FlowPublic, FlowStep } from "./types";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

const flow: FlowPublic = {
  ...flowFixture,
  editing: true,
  editors: [],
  step_origins: [
    {
      key: "intro",
      revision: 4,
      channel: "api",
      changed_at: "2026-10-20T09:00:00Z",
      changed_by_user_id: "user-1",
      assistant_revision: 2
    }
  ]
};
const steps = flow.definition.steps!;
const intro = steps.find((step) => step.key === "intro")!;

function editor(target: { step: FlowStep } | { kind: FlowStep["kind"]; index: number }) {
  const onSaved = vi.fn();
  const onCancel = vi.fn();
  const onDeleted = vi.fn();
  renderInApp(
    <FlowStepEditor
      flow={flow}
      target={target}
      names={names}
      wide={false}
      onSaved={onSaved}
      onCancel={onCancel}
      onOpenRun={() => {}}
      onDeleted={onDeleted}
    />
  );
  return { onSaved, onCancel, onDeleted };
}

beforeEach(() => {
  api.GET.mockImplementation((path: string) => {
    if (path === "/api/v1/flows/{id}/revisions/{revision}/") {
      return Promise.resolve({
        response: new Response("{}"),
        data: {
          ...flow,
          flow_id: flow.id,
          revision: 2,
          created_at: "2026-10-20T08:30:00Z",
          principal_type: "user",
          channel: "mcp",
          changes: { is_initial: false },
          definition: {
            ...flow.definition,
            steps: steps.map((step) =>
              step.key === "intro" ? { ...step, template: "Assistentens mall {{previous}}" } : step
            )
          }
        }
      });
    }
    return Promise.resolve({ data: { items: [] }, response: new Response("{}") });
  });
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("FlowStepEditor", () => {
  it("keeps the revision and definition the editor opened even when the flow refetches", async () => {
    api.PATCH.mockResolvedValue({ data: { ...flow, revision: 5 }, response: new Response("{}") });
    const props = {
      flow,
      target: { step: intro },
      wide: false,
      onSaved: vi.fn(),
      onCancel: vi.fn(),
      onOpenRun: vi.fn(),
      onDeleted: vi.fn()
    };
    const { rerender } = renderInApp(<FlowStepEditor {...props} />);
    fireEvent.change(screen.getByLabelText(/Textmall/), { target: { value: "My unsaved text" } });
    rerender(
      <FlowStepEditor
        {...props}
        flow={{ ...flow, revision: 9, definition: { ...flow.definition, steps: [] } }}
      />
    );
    fireEvent.click(screen.getByRole("button", { name: "Spara som utkast" }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    const body = api.PATCH.mock.calls[0]![1].body;
    expect(body.expected_revision).toBe(flow.revision);
    expect(body.definition.steps).toHaveLength(steps.length);
    expect(body.definition.steps[3].template).toBe("My unsaved text");
  });

  it("counts changed fields, saves the whole definition with the step replaced, and reports", async () => {
    api.PATCH.mockResolvedValue({ data: { ...flow, revision: 5 }, response: new Response("{}") });
    const { onSaved } = editor({ step: intro });
    expect(screen.getByText("Inga ändringar i steg 4")).toBeTruthy();
    const save = screen.getByRole("button", { name: "Spara som utkast" }) as HTMLButtonElement;
    expect(save.disabled || save.getAttribute("aria-disabled") === "true").toBe(true);

    fireEvent.change(screen.getByLabelText(/Textmall/), {
      target: { value: "Inledning: {{form.meeting_date}}" }
    });
    expect(screen.getByText("1 fält ändrat i steg 4")).toBeTruthy();
    fireEvent.change(screen.getByLabelText(/Varför ändrar du/), {
      target: { value: "Kortare inledning" }
    });
    fireEvent.click(screen.getByRole("button", { name: "Spara som utkast" }));

    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    const [path, options] = api.PATCH.mock.calls[0]!;
    expect(path).toBe("/api/v1/flows/{id}/");
    expect(options.params.path.id).toBe("flow-1");
    expect(options.body.note).toBe("Kortare inledning");
    const sent = options.body.definition.steps;
    expect(sent.map((step: FlowStep) => step.key)).toEqual(steps.map((step) => step.key));
    expect(sent[3].template).toBe("Inledning: {{form.meeting_date}}");
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("intro"));
    expect(toast.success).toHaveBeenCalledWith("Sparat som revision 5.");
  });

  it("shows the validator's problems at the field they name, the rest as a list", async () => {
    api.PATCH.mockResolvedValue({
      error: {
        message: "The flow definition has problems",
        details: {
          problems: [
            "step 'intro' template: {{steps.nope}} must name an earlier step",
            "the space has no default completion model"
          ]
        }
      },
      response: new Response(null, { status: 422 })
    });
    editor({ step: intro });
    fireEvent.change(screen.getByLabelText(/Textmall/), { target: { value: "{{steps.nope}}" } });
    fireEvent.click(screen.getByRole("button", { name: "Spara som utkast" }));
    await waitFor(() =>
      expect(screen.getByText("{{steps.nope}} must name an earlier step")).toBeTruthy()
    );
    expect(screen.getByText("the space has no default completion model")).toBeTruthy();
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("offers the assistant's version of a field changed by hand and restores it", async () => {
    editor({ step: intro });
    const restore = await screen.findByRole("button", { name: "Återställ Textmall" });
    fireEvent.click(restore);
    expect((screen.getByLabelText(/Textmall/) as HTMLTextAreaElement).value).toBe(
      "Assistentens mall {{previous}}"
    );
    expect(screen.getByText("1 fält ändrat i steg 4")).toBeTruthy();
  });

  it("removes the step after a confirmation that names the steps reading it", async () => {
    api.PATCH.mockResolvedValue({ data: { ...flow, revision: 5 }, response: new Response("{}") });
    const { onDeleted } = editor({ step: intro });
    fireEvent.click(screen.getByRole("button", { name: "Ta bort steget" }));
    const dialog = await screen.findByRole("alertdialog");
    expect(within(dialog).getByText(/Skapa protokoll/)).toBeTruthy();
    fireEvent.click(within(dialog).getByRole("button", { name: "Ta bort steget" }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    const sent = api.PATCH.mock.calls[0]![1].body.definition.steps;
    expect(sent.map((step: FlowStep) => step.key)).not.toContain("intro");
    await waitFor(() => expect(onDeleted).toHaveBeenCalled());
  });

  it("adds a new step at its position with a key made from its name", async () => {
    api.PATCH.mockResolvedValue({ data: { ...flow, revision: 5 }, response: new Response("{}") });
    const { onSaved } = editor({ kind: "compose", index: 2 });
    expect(screen.getAllByText("Nytt steg 3").length).toBeGreaterThan(0);
    fireEvent.click(screen.getByRole("button", { name: "Lägg till steget" }));
    expect(screen.getAllByText("Fyll i fältet.").length).toBeGreaterThan(0);
    expect(api.PATCH).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText(/^Namn/), { target: { value: "Räkna beslut" } });
    fireEvent.click(screen.getByRole("button", { name: "Lägg till steget" }));
    await waitFor(() => expect(api.PATCH).toHaveBeenCalledTimes(1));
    const sent = api.PATCH.mock.calls[0]![1].body.definition.steps;
    expect(sent[2]).toMatchObject({ kind: "compose", key: "rakna_beslut", name: "Räkna beslut" });
    expect(sent).toHaveLength(steps.length + 1);
    await waitFor(() => expect(onSaved).toHaveBeenCalledWith("rakna_beslut"));
  });
});
