// @vitest-environment jsdom
import { cleanup, fireEvent, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import messages from "@/lib/i18n/messages/sv.json";
import type { Schema } from "@/lib/api/models";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";

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

import { KnowledgeSourceViewer } from "./run-knowledge-source";

const BLOB = "GET /api/v1/info-blobs/{id}/";

function reference(): Schema<"FlowRunDebugRagReference"> {
  return {
    id: "blob-1",
    id_short: "blob-1",
    best_score: 0.8,
    matched_chunk_count: 4,
    recorded_passage_count: 3,
    passages: [
      {
        chunk_no: 7,
        score: 0.42,
        text: "Bygglov krävs för tillbyggnad.",
        passage_bytes: 30,
        recorded_bytes: 30,
        recording: "complete",
        disclosure: "text_disclosed"
      },
      {
        chunk_no: 2,
        score: 0.81,
        text: "Ansökan lämnas till nämnden.",
        passage_bytes: 28,
        recorded_bytes: 28,
        recording: "complete",
        disclosure: "text_disclosed"
      },
      {
        chunk_no: 9,
        score: 0.2,
        text: null,
        passage_bytes: 40,
        recorded_bytes: 40,
        recording: "complete",
        disclosure: "text_withheld_sensitive_flow"
      }
    ]
  } as Schema<"FlowRunDebugRagReference">;
}

function renderViewer() {
  return renderInApp(
    <KnowledgeSourceViewer
      reference={reference()}
      name="Plan- och bygglagen"
      open
      onOpenChange={() => {}}
    />
  );
}

beforeEach(() => {
  state.routes = {};
});

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

describe("KnowledgeSourceViewer", () => {
  it("highlights the recorded passages in the source and goes to each one", async () => {
    state.routes[BLOB] = () => ({
      body: {
        id: "blob-1",
        text: "Inledning. Ansökan lämnas till nämnden. Mer text. Bygglov krävs för tillbyggnad. Slut.",
        metadata: {}
      }
    });
    const { baseElement } = renderViewer();

    const document = await screen.findByRole("region", { name: "Dokumentet Plan- och bygglagen" });
    const marks = document.querySelectorAll("mark");
    expect([...marks].map((mark) => mark.textContent)).toEqual([
      "Ansökan lämnas till nämnden.",
      "Bygglov krävs för tillbyggnad."
    ]);
    expect(screen.getByText(/Visade textavsnitt \(2 av 4\)/)).toBeTruthy();
    expect(screen.getByText(/sekretessregler: 1/)).toBeTruthy();

    fireEvent.click(screen.getByRole("button", { name: /Textavsnitt 7/ }));
    expect(window.document.activeElement?.textContent).toBe("Bygglov krävs för tillbyggnad.");
    expect(state.announce).toHaveBeenCalledWith("Textavsnitt 7, 2 av 2");

    fireEvent.click(screen.getByRole("button", { name: messages.flow_run_knowledge_next_match }));
    expect(window.document.activeElement?.textContent).toBe("Ansökan lämnas till nämnden.");
    expect(within(document).getByText("Ansökan lämnas till nämnden.").className).toContain(
      "underline"
    );
    await expectNoAxeViolations(baseElement);
  });

  it("shows the passages recorded with the run when the source cannot be read", async () => {
    state.routes[BLOB] = () => ({ status: 403, body: { message: "Forbidden" } });
    renderViewer();

    expect(
      await screen.findByText(messages.flow_run_knowledge_source_unavailable_showing_recorded)
    ).toBeTruthy();
    expect(screen.getAllByText("Bygglov krävs för tillbyggnad.").length).toBeGreaterThan(0);
    expect(screen.queryByRole("region")).toBeNull();
  });
});
