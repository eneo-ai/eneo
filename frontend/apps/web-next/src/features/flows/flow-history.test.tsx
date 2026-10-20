// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { FlowHistory } from "./flow-history";
import type { FlowPublic, FlowRevisionPublic, FlowRevisionSummaryPublic } from "./types";

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn() }));
const toast = vi.hoisted(() => ({ error: vi.fn(), success: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("@/lib/toast", () => ({ toast }));

const definition: FlowPublic["definition"] = {
  schema_version: 1,
  form_fields: [{ key: "topic", label: "Ämne", type: "text", required: true }],
  steps: [
    {
      kind: "llm",
      key: "summary",
      id: "s1",
      name: "Sammanfatta",
      prompt: "Sammanfatta {{form.topic}}"
    },
    { kind: "compose", key: "intro", id: "s2", name: "Inledning", template: "Om {{form.topic}}" }
  ]
};

const flow: FlowPublic = {
  id: "flow-1",
  space_id: "space-1",
  name: "Veckobrev",
  description: "Skriver veckobrevet.",
  definition,
  published_version: 1,
  has_unpublished_changes: true,
  revision: 3,
  conversation_id: "session-1",
  created_at: "2026-10-20T08:00:00Z",
  updated_at: "2026-10-20T09:00:00Z"
};

const noChanges = {
  is_initial: false,
  name_changed: false,
  description_changed: false,
  form_fields_changed: false,
  steps_added: [],
  steps_removed: [],
  steps_changed: []
};

const revisions: FlowRevisionSummaryPublic[] = [
  {
    flow_id: "flow-1",
    revision: 3,
    name: "Veckobrev",
    created_at: "2026-10-20T09:00:00Z",
    principal_type: "user",
    channel: "mcp",
    note: "Kortare sammanfattning",
    published_version: null,
    changes: { ...noChanges, steps_changed: ["Sammanfatta"] }
  },
  {
    flow_id: "flow-1",
    revision: 2,
    name: "Veckobrev",
    created_at: "2026-10-20T08:30:00Z",
    principal_type: "user",
    channel: "api",
    note: null,
    published_version: 1,
    changes: { ...noChanges, name_changed: true, steps_added: ["Inledning"] }
  },
  {
    flow_id: "flow-1",
    revision: 1,
    name: "Brev",
    created_at: "2026-10-20T08:00:00Z",
    principal_type: "user",
    channel: "mcp",
    note: null,
    published_version: null,
    changes: { ...noChanges, is_initial: true }
  }
];

function detailOf(revision: number): FlowRevisionPublic {
  const summary = revisions.find((row) => row.revision === revision)!;
  return {
    ...summary,
    description: revision === 1 ? "Första beskrivningen" : "Skriver veckobrevet.",
    definition: revision === 1 ? { ...definition, steps: [definition.steps![0]!] } : definition
  };
}

function mockApi() {
  api.GET.mockImplementation(
    (path: string, options: { params: { path: { revision?: number } } }) => {
      if (path === "/api/v1/flows/{id}/revisions/")
        return Promise.resolve({
          data: { items: revisions, count: 3 },
          response: new Response("{}")
        });
      if (path === "/api/v1/flows/{id}/revisions/{revision}/")
        return Promise.resolve({
          data: detailOf(options.params.path.revision!),
          response: new Response("{}")
        });
      return Promise.reject(new Error(`unexpected GET ${path}`));
    }
  );
  api.POST.mockImplementation(() =>
    Promise.resolve({ data: { ...flow, revision: 4 }, response: new Response("{}") })
  );
}

afterEach(() => {
  cleanup();
  vi.resetAllMocks();
});

describe("FlowHistory", () => {
  it("lists every revision newest first with its source, note, changes and publication", async () => {
    mockApi();
    const { container } = renderInApp(<FlowHistory flow={flow} onRestored={() => {}} />);

    const list = await screen.findByRole("list", { name: "Revisioner" });
    const rows = within(list).getAllByRole("listitem");
    expect(rows.map((row) => within(row).getByRole("button").getAttribute("aria-label"))).toEqual([
      "Visa revision 3",
      "Visa revision 2",
      "Visa revision 1"
    ]);
    // The current revision is marked; the published one carries its version.
    expect(within(rows[0]!).getByText("Aktuell")).toBeTruthy();
    expect(within(rows[1]!).getByText("Publicerad v1")).toBeTruthy();
    expect(within(rows[0]!).queryByText("Publicerad v1")).toBeNull();
    // Source, note and the change summary.
    expect(within(rows[0]!).getByText("Kortare sammanfattning")).toBeTruthy();
    expect(within(rows[0]!).getByText("Steg ändrat: Sammanfatta")).toBeTruthy();
    expect(within(rows[0]!).getByText(/Chatt/)).toBeTruthy();
    expect(within(rows[1]!).getByText("Namn ändrat · Steg tillagt: Inledning")).toBeTruthy();
    expect(within(rows[1]!).getByText(/API/)).toBeTruthy();
    expect(within(rows[2]!).getByText("Första versionen")).toBeTruthy();
    await expectNoAxeViolations(container);
  });

  it("shows the current revision read-only without a restore button", async () => {
    mockApi();
    renderInApp(<FlowHistory flow={flow} onRestored={() => {}} />);

    fireEvent.click(await screen.findByRole("button", { name: "Visa revision 3" }));

    expect(await screen.findByRole("heading", { level: 3, name: "Revision 3" })).toBeTruthy();
    expect(screen.getByText("Det här är flödets aktuella revision.")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Återställ" })).toBeNull();
    // The revision's definition, through the read-only definition view.
    expect(screen.getByRole("region", { name: "Steg, körs i ordning" })).toBeTruthy();
    expect(screen.getByText("Sammanfatta")).toBeTruthy();
    expect(screen.getByText("Inledning")).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: "Tillbaka till historiken" }));
    expect(await screen.findByRole("list", { name: "Revisioner" })).toBeTruthy();
  });

  it("restores an older revision after confirmation and returns to the definition", async () => {
    mockApi();
    const onRestored = vi.fn();
    renderInApp(<FlowHistory flow={flow} onRestored={onRestored} />);

    fireEvent.click(await screen.findByRole("button", { name: "Visa revision 1" }));
    expect(await screen.findByRole("heading", { level: 3, name: "Revision 1" })).toBeTruthy();
    // Revision 1 had one step and its own description.
    expect(screen.getByText("Första beskrivningen")).toBeTruthy();
    expect(screen.queryByText("Inledning")).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "Återställ" }));
    const dialog = await screen.findByRole("alertdialog", { name: "Återställ revision 1?" });
    fireEvent.click(within(dialog).getByRole("button", { name: "Återställ" }));

    await waitFor(() => expect(onRestored).toHaveBeenCalledTimes(1));
    expect(api.POST).toHaveBeenCalledWith(
      "/api/v1/flows/{id}/revisions/{revision}/restore/",
      expect.objectContaining({ params: { path: { id: "flow-1", revision: 1 } } })
    );
    expect(toast.success).toHaveBeenCalledWith("Revision 1 återställdes.");
    expect(toast.error).not.toHaveBeenCalled();
  });
});
