// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { EneoUIMessage } from "@/lib/chat/types";
import { expectNoAxeViolations } from "@/test/axe";
import { renderInApp } from "@/test/render";
import { deriveActivity } from "./activity";
import { ActivityPanel, type ActivityTab } from "./activity-panel";
import type { SkillActivationEvidence } from "./turn-debug";

const spies = vi.hoisted(() => ({
  announce: vi.fn(),
  calls: [] as { path: string; params: unknown }[],
  /** Diagnostics answers per message id; a missing id fails with 404. */
  diagnosticsFor: {} as Record<string, unknown>
}));

const evidence: SkillActivationEvidence = {
  effective_mode: "selective",
  available: [
    {
      activation_key: "guide",
      skill_id: "skill-1",
      skill_revision_id: "rev-1",
      revision_number: 3,
      content_digest: "sha256:abc",
      position: 0,
      source: "space",
      display_name: "Upphandlingsguide",
      slug: "upphandlingsguide"
    }
  ],
  blocked: [],
  initially_active: [],
  accepted: ["guide"],
  repeated: [],
  rejected: [],
  selected_model_id: "model-1",
  selected_model_route: "anthropic/claude-haiku-4-5",
  skill_context_tokens: 400,
  skill_context_token_limit: 1000,
  token_count_source: "litellm",
  activation_rounds: 1,
  selection_latency_ms: 42
};

const savedMessage = (id: string, question: string) => ({
  id,
  created_at: "2026-10-01T08:30:00Z",
  question,
  answer: `Svar på ${question}`,
  completion_model: {
    id: "model-1",
    name: "claude-haiku-4-5",
    nickname: "Claude Haiku 4.5",
    litellm_model_name: "anthropic/claude-haiku-4-5"
  },
  references: [
    { id: "blob-1", metadata: { title: "LOU 19 kap.", url: "https://riksdagen.se/lou" } }
  ],
  files: [],
  generated_files: [],
  tools: { assistants: [] },
  tool_calls: [
    {
      server_name: "lou",
      tool_name: "lou_troskelvarden",
      result_status: "succeeded",
      is_internal: false,
      meta: { "gen_ai.provider.name": "anthropic", "gen_ai.usage.input_tokens": 120 }
    }
  ],
  num_tokens_question: 1200,
  num_tokens_answer: 300
});

vi.mock("@/lib/api/browser", () => ({
  browserApi: {
    GET: vi.fn(async (path: string, init?: { params?: { path?: Record<string, string> } }) => {
      spies.calls.push({ path, params: init?.params });
      if (path === "/api/v1/conversations/{session_id}/") {
        return {
          data: {
            id: "s-1",
            name: "Samtal",
            messages: [savedMessage("m-1", "Vad gäller?"), savedMessage("m-2", "Och kommuner?")]
          },
          response: new Response()
        };
      }
      const messageId = init?.params?.path?.message_id ?? "";
      if (messageId in spies.diagnosticsFor) {
        return {
          data: {
            session_id: "s-1",
            message_id: messageId,
            ...(spies.diagnosticsFor[messageId] as object)
          },
          response: new Response()
        };
      }
      return {
        data: undefined,
        error: { message: "Not found" },
        response: new Response(null, { status: 404 })
      };
    })
  }
}));
vi.mock("@astryxdesign/core/hooks", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@astryxdesign/core/hooks")>()),
  useAnnounce: () => spies.announce
}));

afterEach(() => {
  cleanup();
  spies.announce.mockReset();
  spies.calls.length = 0;
  spies.diagnosticsFor = {};
});

const answer: EneoUIMessage = {
  id: "m-2",
  role: "assistant",
  parts: [{ type: "text", text: "Ja, även kommuner.", state: "done" }]
};

function Harness({
  initialTab = "steps",
  messageId = "m-2",
  onSelectTurn = () => {},
  onClose = () => {}
}: {
  initialTab?: ActivityTab;
  messageId?: string;
  onSelectTurn?: (messageId: string) => void;
  onClose?: () => void;
}) {
  const [tab, setTab] = useState<ActivityTab>(initialTab);
  return (
    <ActivityPanel
      variant="side"
      messageId={messageId}
      activity={deriveActivity({ ...answer, id: messageId }, {})}
      durations={null}
      sessionId="s-1"
      tab={tab}
      onTabChange={setTab}
      focusSource={null}
      debug={{ sessionId: "s-1", onSelectTurn }}
      onClose={onClose}
    />
  );
}

function debugPanel() {
  return screen.getByRole("tabpanel", { name: "Felsök" });
}

describe("Felsök tab", () => {
  it("loads the saved turn and its diagnostics only when the tab opens", async () => {
    spies.diagnosticsFor["m-2"] = { skill_activation: evidence };
    renderInApp(<Harness />);
    expect(spies.calls).toEqual([]);

    fireEvent.click(screen.getByRole("tab", { name: "Felsök" }));
    await waitFor(() => expect(spies.calls).toHaveLength(2));
    expect(spies.calls.map((call) => call.path)).toEqual([
      "/api/v1/conversations/{session_id}/",
      "/api/v1/conversations/{session_id}/messages/{message_id}/diagnostics/"
    ]);

    const panel = debugPanel();
    expect(await within(panel).findByText("Meddelande 2 av 2")).toBeTruthy();
    expect(spies.announce).toHaveBeenCalledWith("Felsökningsinformationen har lästs in");

    // The summary: display name, counts and the technical ids with copy buttons.
    expect(within(panel).getByText("Claude Haiku 4.5")).toBeTruthy();
    expect(within(panel).getByText("1 200")).toBeTruthy();
    expect(within(panel).getByText("300")).toBeTruthy();
    expect(within(panel).getByText("anthropic/claude-haiku-4-5")).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "Kopiera Modellroute" })).toBeTruthy();
    expect(within(panel).getByRole("button", { name: "Kopiera Modell-id" })).toBeTruthy();

    // Tool calls with the provider usage from their metadata.
    expect(within(panel).getByText(/Anrop 1/)).toBeTruthy();
    expect(within(panel).getByText("lou_troskelvarden", { exact: false })).toBeTruthy();
    expect(within(panel).getByText("anthropic")).toBeTruthy();
    expect(within(panel).getByText("120")).toBeTruthy();

    // Knowledge references and the Skill activation evidence.
    expect(within(panel).getByText(/LOU 19 kap\./)).toBeTruthy();
    expect(within(panel).getByText("1 skill tillgänglig · 1 aktiverad")).toBeTruthy();
    expect(within(panel).getByText("Upphandlingsguide")).toBeTruthy();
    expect(within(panel).getByText("Aktiverad vid behov")).toBeTruthy();
    expect(within(panel).getByRole("progressbar", { name: "Tokenbudget för skills" })).toBeTruthy();
    expect(within(panel).getByText("400 av 1 000")).toBeTruthy();
  });

  it("explains a turn saved before Skill evidence existed", async () => {
    spies.diagnosticsFor["m-2"] = { skill_activation: null };
    renderInApp(<Harness initialTab="debug" />);
    expect(await screen.findByText("Underlag för skills saknas")).toBeTruthy();
    expect(screen.queryByText("Aktivering av skills")).toBeNull();
  });

  it("steps between the saved turns of the conversation", async () => {
    spies.diagnosticsFor["m-1"] = { skill_activation: null };
    const onSelectTurn = vi.fn();
    renderInApp(<Harness initialTab="debug" messageId="m-1" onSelectTurn={onSelectTurn} />);
    const panel = debugPanel();
    expect(await within(panel).findByText("Meddelande 1 av 2")).toBeTruthy();

    const previous = within(panel).getByRole("button", { name: "Föregående meddelande" });
    const next = within(panel).getByRole("button", { name: "Nästa meddelande" });
    expect(
      previous.getAttribute("aria-disabled") ?? String(previous.hasAttribute("disabled"))
    ).not.toBe("false");
    fireEvent.click(next);
    expect(onSelectTurn).toHaveBeenCalledWith("m-2");
  });

  it("says the turn is still being saved when the conversation does not have it yet", async () => {
    spies.diagnosticsFor["m-live"] = { skill_activation: null };
    renderInApp(<Harness initialTab="debug" messageId="m-live" />);
    expect(await screen.findByText("Sparar felsökningsinformation")).toBeTruthy();
    const retry = screen.getByRole("button", { name: "Försök igen" });
    const before = spies.calls.length;
    fireEvent.click(retry);
    await waitFor(() => expect(spies.calls.length).toBeGreaterThan(before));
  });

  it("offers a retry when the diagnostics cannot be loaded", async () => {
    renderInApp(<Harness initialTab="debug" />);
    expect(await screen.findByRole("alert")).toBeTruthy();
    expect(screen.getByRole("button", { name: "Försök igen" })).toBeTruthy();
    expect(spies.announce).not.toHaveBeenCalledWith("Felsökningsinformationen har lästs in");
  });

  it("copies a technical value and closes on Escape", async () => {
    spies.diagnosticsFor["m-2"] = { skill_activation: evidence };
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
    const onClose = vi.fn();
    renderInApp(<Harness initialTab="debug" onClose={onClose} />);
    const copy = await screen.findByRole("button", { name: "Kopiera Modellroute" });
    fireEvent.click(copy);
    await waitFor(() => expect(writeText).toHaveBeenCalledWith("anthropic/claude-haiku-4-5"));

    copy.focus();
    fireEvent.keyDown(copy, { key: "Escape" });
    expect(onClose).toHaveBeenCalled();
  });

  it("has no axe violations", async () => {
    spies.diagnosticsFor["m-2"] = { skill_activation: evidence };
    renderInApp(<Harness initialTab="debug" />);
    await screen.findByText("Meddelande 2 av 2");
    await expectNoAxeViolations(document.body);
  });
});
