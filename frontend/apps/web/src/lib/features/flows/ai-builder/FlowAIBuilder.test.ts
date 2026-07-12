// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

// The composer reads app-shell contexts (upload limits, API client) that only
// the real layout provides; stub the minimum it touches.
vi.mock("$lib/core/AppContext", () => ({
  getAppContext: () => ({
    limits: { attachments: { formats: [] } }
  })
}));
vi.mock("$lib/core/Eneo", () => ({
  getEneo: () => ({})
}));

import FlowAIBuilderHarness from "./test-harnesses/FlowAIBuilderHarness.svelte";
import type { AIBuilderClientTransport } from "./FlowAIBuilderDriver";

function recoveryHarness(
  state: "open" | "processing" | "failed_before_provider" | "provider_outcome_unknown",
  options: { failRefresh?: boolean } = {}
): {
  fetch: AIBuilderClientTransport["fetch"];
  stream: AIBuilderClientTransport["stream"];
} {
  const draft = {
    session_id: "draft-recovery",
    space_id: "space-1",
    status: "chatting" as const,
    target_kind: "create" as const,
    flow_id: null,
    latest_plan_id: null,
    draft_title: "Recovered draft",
    created_at: "2026-07-10T20:00:00Z",
    updated_at: "2026-07-10T20:05:00Z"
  };
  const retryRequest = {
    client_turn_id: "11111111-1111-4111-8111-111111111111",
    message: "Build a flow",
    ui_language: "sv",
    acknowledge_duplicate_provider_spend: false
  };
  const session = {
    ...draft,
    conversation: [
      {
        message_id: "user-recovery",
        role: "user" as const,
        content: "Build a flow",
        timestamp: "2026-07-10T20:00:00Z"
      }
    ],
    latest_turn: {
      client_turn_id: retryRequest.client_turn_id,
      state,
      user_message_id: "11111111-1111-4111-8111-111111111112",
      error: null,
      requires_duplicate_provider_spend_acknowledgement: state === "provider_outcome_unknown",
      retry_request: retryRequest
    }
  };
  let sessionReadCount = 0;
  const fetch = vi.fn();
  fetch.mockImplementation(async (path: string, init?: { method?: string }) => {
    if (path.endsWith("/models")) return { models: [], default_model_id: null };
    if (path === "/api/v1/flows/ai-builder/sessions" && init?.method === "get") {
      return { sessions: [draft] };
    }
    if (path === "/api/v1/flows/ai-builder/sessions/{session_id}") {
      sessionReadCount += 1;
      if (sessionReadCount > 1 && options.failRefresh) {
        throw new Error("session refresh unavailable");
      }
      return sessionReadCount === 1
        ? session
        : { ...session, latest_turn: { ...session.latest_turn, state: "committed" as const } };
    }
    return {};
  });
  const stream = vi.fn(async (_path, _init, handlers) => {
    handlers.onMessage({ event: "done", data: "" });
    handlers.onClose();
  }) as AIBuilderClientTransport["stream"];
  return { fetch, stream };
}

// jsdom in the server project does not always provide rAF or the Web
// Animations API; the composer's focus() and the resume banner's fade
// transition go through them.
globalThis.requestAnimationFrame ??= ((cb: FrameRequestCallback) =>
  setTimeout(() => cb(0), 0)) as never;
Element.prototype.animate ??= (() => ({
  cancel() {},
  finished: Promise.resolve(),
  onfinish: null
})) as never;

afterEach(() => {
  cleanup();
});

// A resumable create session whose latest plan is already proposed: resuming
// it drives the shell straight into the plan-review state.
function planSessionHarness(): {
  fetch: AIBuilderClientTransport["fetch"];
  stream: AIBuilderClientTransport["stream"];
} {
  const draft = {
    session_id: "plan-session",
    space_id: "space-1",
    status: "awaiting_approval" as const,
    target_kind: "create" as const,
    flow_id: null,
    latest_plan_id: "plan-1",
    draft_title: "Sammanfatta till PDF",
    created_at: "2026-07-11T09:00:00Z",
    updated_at: "2026-07-11T09:05:00Z"
  };
  const session = {
    ...draft,
    conversation: [
      {
        message_id: "m-1",
        role: "user" as const,
        content: "Sammanfatta rapporter till en PDF",
        timestamp: "2026-07-11T09:00:00Z"
      },
      {
        message_id: "m-2",
        role: "assistant" as const,
        content: "Här är mitt förslag:",
        timestamp: "2026-07-11T09:05:00Z"
      }
    ],
    latest_turn: null
  };
  const plan = {
    plan_id: "plan-1",
    status: "proposed",
    proposal: {
      spec: {
        flow_name: "Sammanfatta till PDF",
        flow_description: "Tar emot text och levererar en PDF.",
        steps: [],
        form_fields: null
      },
      assumptions: [],
      lint_warnings: [],
      risk_acknowledgments: [],
      description_override_manual: false,
      edit: null
    }
  };
  const fetch = vi.fn(async (path: string) => {
    if (path.endsWith("/models")) return { models: [], default_model_id: null };
    if (path === "/api/v1/flows/ai-builder/sessions") return { sessions: [draft] };
    if (path === "/api/v1/flows/ai-builder/sessions/{session_id}") return session;
    if (path === "/api/v1/flows/ai-builder/plans/{plan_id}") return plan;
    return {};
  }) as unknown as AIBuilderClientTransport["fetch"];
  const stream = vi.fn() as unknown as AIBuilderClientTransport["stream"];
  return { fetch, stream };
}

describe("FlowAIBuilder shell layout", () => {
  it("activates the Plan view when a plan arrives and keeps both panes mounted", async () => {
    render(FlowAIBuilderHarness, { transport: planSessionHarness() });

    const planTab = await screen.findByRole("button", { name: m.ai_builder_pane_tab_plan() });
    const taskTab = screen.getByRole("button", { name: m.ai_builder_pane_tab_task() });

    // Rising edge of plan content auto-selects the plan view in narrow layouts.
    expect(planTab.getAttribute("aria-pressed")).toBe("true");
    expect(taskTab.getAttribute("aria-pressed")).toBe("false");

    // Both panes stay in the DOM regardless of the active view, so pane-local
    // state survives switching (handoff §6: mode/tab switches lose no state).
    expect(document.getElementById("ai-builder-task-pane")).toBeTruthy();
    expect(document.getElementById("ai-builder-plan-pane")).toBeTruthy();

    await fireEvent.click(taskTab);
    expect(taskTab.getAttribute("aria-pressed")).toBe("true");
    expect(planTab.getAttribute("aria-pressed")).toBe("false");
    expect(document.getElementById("ai-builder-plan-pane")).toBeTruthy();
  });

  it("preserves the composer draft across pane switches", async () => {
    render(FlowAIBuilderHarness, { transport: planSessionHarness() });

    const taskTab = await screen.findByRole("button", { name: m.ai_builder_pane_tab_task() });
    const planTab = screen.getByRole("button", { name: m.ai_builder_pane_tab_plan() });
    await fireEvent.click(taskTab);

    const textbox = screen.getByRole("textbox") as HTMLTextAreaElement;
    await fireEvent.input(textbox, { target: { value: "Lägg till en sammanfattning" } });

    await fireEvent.click(planTab);
    await fireEvent.click(taskTab);

    expect((screen.getByRole("textbox") as HTMLTextAreaElement).value).toBe(
      "Lägg till en sammanfattning"
    );
  });

  it("renders both phase-indicator forms: the full bar and the narrow text form", async () => {
    render(FlowAIBuilderHarness, { transport: planSessionHarness() });

    await screen.findByRole("button", { name: m.ai_builder_pane_tab_plan() });

    // Which form is visible is decided by CSS container queries (not testable
    // in jsdom); the contract here is that both exist with the right content
    // and the compact form reflects the current phase.
    expect(screen.getByRole("navigation", { name: m.ai_builder_progress_aria() })).toBeTruthy();
    expect(
      screen.getByText(
        m.ai_builder_phase_step_of({ step: 3, total: 3, label: m.ai_builder_phase_ready() })
      )
    ).toBeTruthy();
  });
});

describe("FlowAIBuilder", () => {
  it("auto-resumes a single matching create draft instead of starting a new chat", async () => {
    const draft = {
      session_id: "draft-1",
      space_id: "space-1",
      status: "chatting",
      target_kind: "create",
      flow_id: null,
      latest_plan_id: null,
      draft_title: "Recovered draft",
      created_at: "2026-03-15T10:00:00Z",
      updated_at: "2026-03-15T10:05:00Z"
    };
    const fetch = vi
      .fn()
      .mockResolvedValueOnce({ sessions: [draft] })
      .mockResolvedValueOnce({
        ...draft,
        conversation: [
          {
            role: "assistant",
            content: "Welcome back to your draft.",
            timestamp: "2026-03-15T10:05:00Z"
          }
        ]
      })
      .mockResolvedValueOnce({ models: [], default_model_id: null })
      .mockResolvedValueOnce({ sessions: [draft] });

    render(FlowAIBuilderHarness, {
      transport: {
        fetch,
        stream: vi.fn()
      }
    });

    expect(await screen.findByText(m.ai_builder_resumed_from())).toBeTruthy();
    expect(screen.getByText("Welcome back to your draft.")).toBeTruthy();
    expect(fetch).not.toHaveBeenCalledWith(
      "/api/v1/flows/ai-builder/sessions",
      expect.objectContaining({ method: "post" })
    );
    expect(fetch).toHaveBeenCalledWith("/api/v1/flows/ai-builder/sessions/{session_id}", {
      method: "get",
      params: { path: { session_id: "draft-1" } }
    });
  });

  it("prefers a seeded prompt over draft recovery and prefills the composer", async () => {
    const draft = {
      session_id: "draft-1",
      space_id: "space-1",
      status: "chatting",
      target_kind: "create",
      flow_id: null,
      latest_plan_id: null,
      draft_title: "Recovered draft",
      created_at: "2026-03-15T10:00:00Z",
      updated_at: "2026-03-15T10:05:00Z"
    };
    const freshSession = {
      session_id: "fresh-1",
      space_id: "space-1",
      status: "chatting",
      target_kind: "create",
      flow_id: null,
      latest_plan_id: null,
      conversation: [],
      created_at: "2026-03-15T11:00:00Z",
      updated_at: "2026-03-15T11:00:00Z"
    };
    const fetch = vi.fn((async (...args: unknown[]) => {
      const [url, opts] = args as [string, { method?: string } | undefined];
      if (url === "/api/v1/flows/ai-builder/sessions" && opts?.method === "post") {
        return freshSession;
      }
      if (url === "/api/v1/flows/ai-builder/sessions" && opts?.method === "get") {
        return { sessions: [draft] };
      }
      if (url.includes("/models")) {
        return { models: [], default_model_id: null };
      }
      if (url.includes("{session_id}")) {
        return freshSession;
      }
      return {};
    }) as unknown as AIBuilderClientTransport["fetch"]);
    const stream = vi.fn();

    render(FlowAIBuilderHarness, {
      transport: { fetch, stream },
      initialPrompt: "Sammanfatta uppladdade rapporter till en PDF"
    });

    // The seed lands in the composer for review; nothing is auto-sent.
    expect(
      await screen.findByDisplayValue("Sammanfatta uppladdade rapporter till en PDF")
    ).toBeTruthy();
    expect(stream).not.toHaveBeenCalled();

    // A fresh session is forced; the recoverable draft is neither listed nor resumed.
    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/flows/ai-builder/sessions",
      expect.objectContaining({
        method: "post",
        requestBody: {
          "application/json": expect.objectContaining({ force_new: true, target_kind: "create" })
        }
      })
    );
    expect(fetch).not.toHaveBeenCalledWith(
      "/api/v1/flows/ai-builder/sessions/{session_id}",
      expect.objectContaining({ params: { path: { session_id: "draft-1" } } })
    );
    expect(screen.queryByText(m.ai_builder_resumed_from())).toBeNull();
  });

  it("offers a safe exact retry when no provider work started", async () => {
    const transport = recoveryHarness("failed_before_provider");
    render(FlowAIBuilderHarness, { transport });

    expect(await screen.findByText(m.ai_builder_turn_failed_before_provider_title())).toBeTruthy();
    const retry = screen.getByRole("button", { name: m.ai_builder_turn_retry() });
    await fireEvent.click(retry);

    expect(transport.stream).toHaveBeenCalledOnce();
    expect(vi.mocked(transport.stream).mock.calls[0]?.[1].requestBody["application/json"]).toEqual(
      expect.objectContaining({
        client_turn_id: "11111111-1111-4111-8111-111111111111",
        message: "Build a flow",
        acknowledge_duplicate_provider_spend: false
      })
    );
  });

  it("requires explicit possible-cost acknowledgement for an unknown outcome", async () => {
    const transport = recoveryHarness("provider_outcome_unknown");
    render(FlowAIBuilderHarness, { transport });

    expect(
      await screen.findByText(m.ai_builder_turn_provider_outcome_unknown_description())
    ).toBeTruthy();
    const retry = screen.getByRole("button", {
      name: m.ai_builder_turn_retry_with_cost_acknowledgement()
    });
    await fireEvent.click(retry);

    expect(transport.stream).toHaveBeenCalledOnce();
    expect(vi.mocked(transport.stream).mock.calls[0]?.[1].requestBody["application/json"]).toEqual(
      expect.objectContaining({
        client_turn_id: "11111111-1111-4111-8111-111111111111",
        acknowledge_duplicate_provider_spend: true
      })
    );
  });

  it("explains an active durable turn and refreshes before enabling another message", async () => {
    const transport = recoveryHarness("processing");
    render(FlowAIBuilderHarness, { transport });

    expect(await screen.findByText(m.ai_builder_turn_active_title())).toBeTruthy();
    const textbox = screen.getByRole("textbox") as HTMLTextAreaElement;
    expect(textbox.disabled).toBe(true);

    await fireEvent.click(screen.getByRole("button", { name: m.refresh() }));

    expect(textbox.disabled).toBe(false);
    expect(transport.stream).not.toHaveBeenCalled();
  });

  it("keeps active work blocked and explains when status refresh fails", async () => {
    const transport = recoveryHarness("processing", { failRefresh: true });
    render(FlowAIBuilderHarness, { transport });

    expect(await screen.findByText(m.ai_builder_turn_active_title())).toBeTruthy();
    const textbox = screen.getByRole("textbox") as HTMLTextAreaElement;

    await fireEvent.click(screen.getByRole("button", { name: m.refresh() }));

    expect(textbox.disabled).toBe(true);
    expect(await screen.findByText(m.ai_builder_turn_refresh_failed())).toBeTruthy();
    expect(screen.getByRole("button", { name: m.refresh() })).toBeTruthy();
  });
});
