// @vitest-environment jsdom

import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
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
  getEneo: () => ({ files: { delete: vi.fn().mockResolvedValue(undefined) } })
}));

import FlowAIBuilderHarness from "./test-harnesses/FlowAIBuilderHarness.svelte";
import type { AIBuilderClientTransport } from "./FlowAIBuilderDriver";
import type { FlowAIBuilderService } from "./FlowAIBuilderService.svelte.ts";

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
  // Composer drafts persist per session id; tests share ids across cases.
  localStorage.clear();
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
        timestamp: "2026-07-11T09:05:00Z",
        requirements_summary: {
          requirements_version: "v1",
          summary: "Skapa ett beslutsunderlag som PDF.",
          key_decisions: [{ topic: "Slutresultat", decision: "PDF-dokument" }],
          input_description: "Text vid körning",
          output_description: "PDF med rekommendation",
          assumptions: ["Svenska som språk"],
          manual_setup_notes: []
        }
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

// Capture every composer send as an awaitable promise. The composer awaits the
// same promise FIRST, so `await sends[n]` in a test resumes strictly after the
// composer's completion handler for that attempt has executed — a
// deterministic receipt, no sleeps.
function interceptSends(service: FlowAIBuilderService) {
  const sends: ReturnType<FlowAIBuilderService["sendMessage"]>[] = [];
  const original = service.sendMessage.bind(service);
  service.sendMessage = ((...args: Parameters<FlowAIBuilderService["sendMessage"]>) => {
    const promise = original(...args);
    sends.push(promise);
    return promise;
  }) as FlowAIBuilderService["sendMessage"];
  return sends;
}

// Two plan-review sessions behind one transport, addressable by id, so a test
// can drive live session switches through service.resumeSession.
function twoSessionHarness(): { transport: AIBuilderClientTransport } {
  const base = planSessionHarness();
  const makeSession = (sessionId: string) => ({
    session_id: sessionId,
    space_id: "space-1",
    status: "awaiting_approval" as const,
    target_kind: "create" as const,
    flow_id: null,
    latest_plan_id: "plan-1",
    draft_title: sessionId,
    created_at: "2026-07-11T09:00:00Z",
    updated_at: "2026-07-11T09:05:00Z",
    conversation: [
      {
        message_id: `${sessionId}-m1`,
        role: "user" as const,
        content: "Sammanfatta rapporter till en PDF",
        timestamp: "2026-07-11T09:00:00Z"
      }
    ],
    latest_turn: null
  });
  const originalFetch = base.fetch;
  const fetch = vi.fn(
    async (path: string, init?: { params?: { path?: { session_id?: string } } }) => {
      if (path === "/api/v1/flows/ai-builder/sessions/{session_id}") {
        return makeSession(init?.params?.path?.session_id ?? "plan-session");
      }
      return await (originalFetch as (p: string, i?: unknown) => Promise<unknown>)(path, init);
    }
  ) as unknown as AIBuilderClientTransport["fetch"];
  return { transport: { fetch, stream: base.stream } };
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

describe("FlowAIBuilder plan-review left pane", () => {
  it("replaces the transcript with the structured task pane in plan review", async () => {
    render(FlowAIBuilderHarness, { transport: planSessionHarness() });

    expect(await screen.findByRole("heading", { name: m.ai_builder_task_heading() })).toBeTruthy();
    expect(screen.getAllByText("Sammanfatta rapporter till en PDF").length).toBeGreaterThan(0);
    expect(
      screen.getByRole("heading", { name: m.ai_builder_decisions_from_answers() })
    ).toBeTruthy();
    // The raw transcript is folded into a collapsed conversation section.
    const conversationTrigger = screen.getByRole("button", {
      name: new RegExp(
        m.ai_builder_conversation_heading({ count: 2 }).replace(/[.*+?^${}()|[\]\\]/g, "\\$&")
      )
    });
    expect(conversationTrigger.getAttribute("aria-expanded")).toBe("false");
  });

  it("runs the composer in refinement mode: hint, Ctrl+Enter submit", async () => {
    const transport = planSessionHarness();
    const stream = vi.fn(async (_path, _init, handlers) => {
      handlers.onMessage({ event: "done", data: "" });
      handlers.onClose();
    }) as AIBuilderClientTransport["stream"];
    transport.stream = stream;
    render(FlowAIBuilderHarness, { transport });

    await screen.findByRole("heading", { name: m.ai_builder_task_heading() });
    expect(screen.getByText(m.ai_builder_refine_hint())).toBeTruthy();

    const textbox = screen.getByRole("textbox", {
      name: m.ai_builder_refine_label()
    }) as HTMLTextAreaElement;
    expect(textbox.placeholder).toBe(m.ai_builder_refine_placeholder());

    await fireEvent.input(textbox, { target: { value: "Lägg till en sammanfattning" } });
    // Plain Enter must NOT send in refinement mode (the hint says Ctrl+Retur).
    await fireEvent.keyDown(textbox, { key: "Enter" });
    expect(stream).not.toHaveBeenCalled();

    await fireEvent.keyDown(textbox, { key: "Enter", ctrlKey: true });
    expect(stream).toHaveBeenCalledOnce();
    expect(vi.mocked(stream).mock.calls[0]?.[1].requestBody["application/json"]).toEqual(
      expect.objectContaining({ message: "Lägg till en sammanfattning" })
    );
  });

  it("counts down from 3 500 characters and blocks sending over 4 000", async () => {
    render(FlowAIBuilderHarness, { transport: planSessionHarness() });

    await screen.findByRole("heading", { name: m.ai_builder_task_heading() });
    const textbox = screen.getByRole("textbox", {
      name: m.ai_builder_refine_label()
    }) as HTMLTextAreaElement;

    await fireEvent.input(textbox, { target: { value: "a".repeat(3600) } });
    expect(screen.getByText(/3\s*600\s*\/\s*4\s*000/)).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: m.ai_builder_send() }) as HTMLButtonElement).disabled
    ).toBe(false);

    await fireEvent.input(textbox, { target: { value: "a".repeat(4001) } });
    expect(textbox.getAttribute("aria-invalid")).toBe("true");
    expect(screen.getByText(m.ai_builder_refine_over_limit_tip())).toBeTruthy();
    expect(
      (screen.getByRole("button", { name: m.ai_builder_send() }) as HTMLButtonElement).disabled
    ).toBe(true);
  });

  it("persists the composer draft per session and restores it on remount", async () => {
    render(FlowAIBuilderHarness, { transport: planSessionHarness() });

    await screen.findByRole("heading", { name: m.ai_builder_task_heading() });
    const textbox = screen.getByRole("textbox", {
      name: m.ai_builder_refine_label()
    }) as HTMLTextAreaElement;
    await fireEvent.input(textbox, { target: { value: "Utkast som ska överleva" } });

    const stored = JSON.parse(localStorage.getItem("eneo:ai-builder:draft:plan-session") ?? "{}");
    expect(stored.text).toBe("Utkast som ska överleva");

    cleanup();
    render(FlowAIBuilderHarness, { transport: planSessionHarness() });

    expect(await screen.findByDisplayValue("Utkast som ska överleva")).toBeTruthy();
    // The note lives in the refinement meta row, which appears once the plan
    // fetch lands and flips the composer into refinement mode.
    expect(await screen.findByText(m.ai_builder_draft_persistence_note())).toBeTruthy();
  });

  it("keeps the draft in the textarea and in storage when the send fails", async () => {
    const transport = planSessionHarness();
    transport.stream = vi.fn(async () => {
      throw new Error("stream transport down");
    }) as AIBuilderClientTransport["stream"];
    render(FlowAIBuilderHarness, { transport });

    await screen.findByRole("heading", { name: m.ai_builder_task_heading() });
    const textbox = screen.getByRole("textbox", {
      name: m.ai_builder_refine_label()
    }) as HTMLTextAreaElement;

    await fireEvent.input(textbox, { target: { value: "Får inte försvinna" } });
    await fireEvent.keyDown(textbox, { key: "Enter", ctrlKey: true });
    await waitFor(() => expect(transport.stream).toHaveBeenCalledOnce());

    // Composer text is never discarded on a failure edge (§4).
    await waitFor(() => expect(textbox.value).toBe("Får inte försvinna"));
    const stored = JSON.parse(localStorage.getItem("eneo:ai-builder:draft:plan-session") ?? "{}");
    expect(stored.text).toBe("Får inte försvinna");
  });

  it("never leaks a draft across a live session switch (A→B→A)", async () => {
    const { transport } = twoSessionHarness();
    let service: FlowAIBuilderService | undefined;
    render(FlowAIBuilderHarness, {
      transport,
      onservice: (instance: FlowAIBuilderService) => (service = instance)
    });

    await screen.findByRole("heading", { name: m.ai_builder_task_heading() });
    const textbox = () =>
      screen.getByRole("textbox", { name: m.ai_builder_refine_label() }) as HTMLTextAreaElement;
    await fireEvent.input(textbox(), { target: { value: "Utkast för session A" } });

    await service!.resumeSession("plan-session-b");
    // B starts empty — A's text must not follow along or be written under B.
    await waitFor(() => expect(textbox().value).toBe(""));
    expect(localStorage.getItem("eneo:ai-builder:draft:plan-session-b")).toBeNull();
    expect(
      JSON.parse(localStorage.getItem("eneo:ai-builder:draft:plan-session") ?? "{}").text
    ).toBe("Utkast för session A");

    await fireEvent.input(textbox(), { target: { value: "Utkast för session B" } });
    await service!.resumeSession("plan-session");
    await waitFor(() => expect(textbox().value).toBe("Utkast för session A"));
    expect(
      JSON.parse(localStorage.getItem("eneo:ai-builder:draft:plan-session-b") ?? "{}").text
    ).toBe("Utkast för session B");
  });

  it("restores completed unsent uploads from the draft record", async () => {
    localStorage.setItem(
      "eneo:ai-builder:draft:plan-session",
      JSON.stringify({
        text: "",
        files: [{ id: "file-9", name: "underlag.pdf", size: 2048, mimetype: "application/pdf" }]
      })
    );
    render(FlowAIBuilderHarness, { transport: planSessionHarness() });

    await screen.findByRole("heading", { name: m.ai_builder_task_heading() });
    expect(await screen.findByTitle("underlag.pdf")).toBeTruthy();

    // Removal drops the reference from the record (and never re-sends it).
    await fireEvent.click(screen.getByRole("button", { name: m.remove_attachment() }));
    await waitFor(() => expect(screen.queryByTitle("underlag.pdf")).toBeNull());
    expect(localStorage.getItem("eneo:ai-builder:draft:plan-session")).toBeNull();
  });

  it("submits a restored file-only draft and clears the record only on delivery", async () => {
    localStorage.setItem(
      "eneo:ai-builder:draft:plan-session",
      JSON.stringify({
        text: "",
        files: [{ id: "file-9", name: "underlag.pdf", size: 2048, mimetype: "application/pdf" }]
      })
    );
    const transport = planSessionHarness();
    const stream = vi.fn(async (_path, _init, handlers) => {
      handlers.onMessage({ event: "done", data: "" });
      handlers.onClose();
    }) as AIBuilderClientTransport["stream"];
    transport.stream = stream;
    render(FlowAIBuilderHarness, { transport });

    await screen.findByRole("heading", { name: m.ai_builder_task_heading() });
    await screen.findByTitle("underlag.pdf");

    const send = screen.getByRole("button", { name: m.ai_builder_send() }) as HTMLButtonElement;
    expect(send.disabled).toBe(false);
    await fireEvent.click(send);

    await waitFor(() => expect(stream).toHaveBeenCalledOnce());
    expect(vi.mocked(stream).mock.calls[0]?.[1].requestBody["application/json"]).toEqual(
      expect.objectContaining({ file_ids: ["file-9"] })
    );
    await waitFor(() =>
      expect(localStorage.getItem("eneo:ai-builder:draft:plan-session")).toBeNull()
    );
  });

  it("does not restore a late-failing send into a different session", async () => {
    const { transport } = twoSessionHarness();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    transport.stream = vi.fn(async () => {
      await gate;
      throw new Error("late transport failure");
    }) as AIBuilderClientTransport["stream"];

    let service: FlowAIBuilderService | undefined;
    render(FlowAIBuilderHarness, {
      transport,
      onservice: (instance: FlowAIBuilderService) => (service = instance)
    });

    await screen.findByRole("heading", { name: m.ai_builder_task_heading() });
    const sends = interceptSends(service!);
    const textbox = () =>
      screen.getByRole("textbox", { name: m.ai_builder_refine_label() }) as HTMLTextAreaElement;

    await fireEvent.input(textbox(), { target: { value: "A:s meddelande" } });
    await fireEvent.keyDown(textbox(), { key: "Enter", ctrlKey: true });
    // The optimistic clear must not delete A's durable record mid-flight.
    expect(
      JSON.parse(localStorage.getItem("eneo:ai-builder:draft:plan-session") ?? "{}").text
    ).toBe("A:s meddelande");

    await service!.resumeSession("plan-session-b");
    await waitFor(() => expect(textbox().value).toBe(""));

    release();
    // Deterministic receipt: the composer awaited this same promise first, so
    // its completion handler has run by the time this await resumes.
    expect(await sends[0]).toBe("failed");

    // B's composer and storage stay untouched; A's record survives the failure.
    expect(textbox().value).toBe("");
    expect(localStorage.getItem("eneo:ai-builder:draft:plan-session-b")).toBeNull();
    expect(
      JSON.parse(localStorage.getItem("eneo:ai-builder:draft:plan-session") ?? "{}").text
    ).toBe("A:s meddelande");
  });

  it("resets the shared scroller to the top when the task pane replaces the transcript", async () => {
    const base = planSessionHarness();
    let releasePlan!: () => void;
    const planGate = new Promise<void>((resolve) => (releasePlan = resolve));
    const fetch = vi.fn(async (path: string, init?: unknown) => {
      if (path === "/api/v1/flows/ai-builder/plans/{plan_id}") {
        await planGate;
      }
      return await (base.fetch as (p: string, i?: unknown) => Promise<unknown>)(path, init);
    }) as unknown as AIBuilderClientTransport["fetch"];
    render(FlowAIBuilderHarness, { transport: { fetch, stream: base.stream } });

    // Transcript mode while the plan fetch is still pending; simulate a
    // scrolled-to-bottom transcript.
    const scroller = await screen.findByRole("region", { name: m.ai_builder_task_pane_aria() });
    scroller.scrollTop = 480;
    expect(scroller.scrollTop).toBe(480);

    releasePlan();
    await screen.findByRole("heading", { name: m.ai_builder_task_heading() });
    await waitFor(() => expect(scroller.scrollTop).toBe(0));
  });

  it("keeps a submitted restored file when newer text is typed and the send fails", async () => {
    localStorage.setItem(
      "eneo:ai-builder:draft:plan-session",
      JSON.stringify({
        text: "Skicka med underlaget",
        files: [{ id: "file-9", name: "underlag.pdf", size: 2048, mimetype: "application/pdf" }]
      })
    );
    const transport = planSessionHarness();
    let release!: () => void;
    const gate = new Promise<void>((resolve) => (release = resolve));
    transport.stream = vi.fn(async () => {
      await gate;
      throw new Error("late failure");
    }) as AIBuilderClientTransport["stream"];
    let service: FlowAIBuilderService | undefined;
    render(FlowAIBuilderHarness, {
      transport,
      onservice: (instance: FlowAIBuilderService) => (service = instance)
    });

    await screen.findByRole("heading", { name: m.ai_builder_task_heading() });
    const sends = interceptSends(service!);
    await screen.findByTitle("underlag.pdf");
    const textbox = screen.getByRole("textbox", {
      name: m.ai_builder_refine_label()
    }) as HTMLTextAreaElement;
    expect(textbox.value).toBe("Skicka med underlaget");

    await fireEvent.keyDown(textbox, { key: "Enter", ctrlKey: true });
    // Newer intent typed while the send streams.
    await fireEvent.input(textbox, { target: { value: "Nyare text" } });

    release();
    expect(await sends[0]).toBe("failed");

    // Newer text wins visibly AND the submitted file reference survives, both
    // in the composer and in the durable record.
    expect(textbox.value).toBe("Nyare text");
    expect(screen.getByTitle("underlag.pdf")).toBeTruthy();
    const stored = JSON.parse(localStorage.getItem("eneo:ai-builder:draft:plan-session") ?? "{}");
    expect(stored.text).toBe("Nyare text");
    expect(stored.files).toEqual([
      { id: "file-9", name: "underlag.pdf", size: 2048, mimetype: "application/pdf" }
    ]);
  });

  it("ignores a stale completion while a newer submission is in flight", async () => {
    const { transport } = twoSessionHarness();
    const gates: Array<() => void> = [];
    transport.stream = vi.fn(async () => {
      await new Promise<void>((resolve) => gates.push(resolve));
      throw new Error("transport failure");
    }) as AIBuilderClientTransport["stream"];

    let service: FlowAIBuilderService | undefined;
    render(FlowAIBuilderHarness, {
      transport,
      onservice: (instance: FlowAIBuilderService) => (service = instance)
    });

    await screen.findByRole("heading", { name: m.ai_builder_task_heading() });
    const sends = interceptSends(service!);
    const textbox = () =>
      screen.getByRole("textbox", { name: m.ai_builder_refine_label() }) as HTMLTextAreaElement;

    // A submits and stays in flight.
    await fireEvent.input(textbox(), { target: { value: "A:s meddelande" } });
    await fireEvent.keyDown(textbox(), { key: "Enter", ctrlKey: true });

    // Switch to B and submit there too — B's attempt now owns the slot.
    await service!.resumeSession("plan-session-b");
    await waitFor(() => expect(textbox().value).toBe(""));
    await fireEvent.input(textbox(), { target: { value: "B:s meddelande" } });
    await fireEvent.keyDown(textbox(), { key: "Enter", ctrlKey: true });
    expect(
      JSON.parse(localStorage.getItem("eneo:ai-builder:draft:plan-session-b") ?? "{}").text
    ).toBe("B:s meddelande");

    // A settles first: a stale completion may not clear B's in-flight guard,
    // restore A's text, or touch B's durable record.
    gates[0]!();
    expect(await sends[0]).toBe("failed");
    expect(textbox().value).toBe("");
    // A reactive service update now re-runs the composer's save effect while
    // B's optimistic clear is live; only an intact in-flight guard keeps the
    // empty composer from being mirrored over B's durable record.
    await service!.refreshSession();
    expect(
      JSON.parse(localStorage.getItem("eneo:ai-builder:draft:plan-session-b") ?? "{}").text
    ).toBe("B:s meddelande");

    // B settles as failed: ITS completion restores B's draft.
    gates[1]!();
    expect(await sends[1]).toBe("failed");
    await waitFor(() => expect(textbox().value).toBe("B:s meddelande"));
  });
});

describe("FlowAIBuilder clarification history", () => {
  it("shows the chosen answer on an answered question and collapses superseded summaries", async () => {
    const draft = {
      session_id: "hist-session",
      space_id: "space-1",
      status: "chatting",
      target_kind: "create",
      flow_id: null,
      latest_plan_id: null,
      draft_title: "Sammanfatta dokument",
      created_at: "2026-07-12T09:00:00Z",
      updated_at: "2026-07-12T09:00:00Z"
    };
    const summary = (version: string, summaryText: string) => ({
      requirements_version: version,
      summary: summaryText,
      key_decisions: [{ topic: "Slutresultat", decision: "PDF-dokument" }],
      input_description: "Dokument vid körning",
      output_description: "PDF-dokument",
      assumptions: [],
      manual_setup_notes: []
    });
    const session = {
      ...draft,
      conversation: [
        {
          message_id: "u1",
          role: "user",
          content: "Sammanfatta uppladdade dokument",
          timestamp: "2026-07-12T09:00:00Z"
        },
        {
          message_id: "a1",
          role: "assistant",
          content: "Hur ska rapporten hantera flera källdokument?",
          timestamp: "2026-07-12T09:00:05Z",
          question: {
            question_id: "report_layout",
            question: "Hur ska rapporten hantera flera källdokument?",
            options: [{ id: "per_source", label: "Avsnitt per källa" }],
            selection_mode: "single",
            allow_custom: false
          }
        },
        {
          message_id: "u2",
          role: "user",
          content: "Avsnitt per källa",
          timestamp: "2026-07-12T09:00:10Z",
          question_answer: {
            kind: "structured_question_answer",
            question_id: "report_layout",
            selected_option_ids: ["per_source"]
          }
        },
        {
          message_id: "a2",
          role: "assistant",
          content: "",
          timestamp: "2026-07-12T09:00:15Z",
          requirements_summary: summary("v1", "Första tolkningen.")
        },
        {
          message_id: "a3",
          role: "assistant",
          content: "",
          timestamp: "2026-07-12T09:00:25Z",
          requirements_summary: summary("v2", "Andra tolkningen.")
        }
      ],
      latest_turn: null
    };
    const fetch = vi.fn(async (path: string, init?: { method?: string }) => {
      if (path.endsWith("/models")) return { models: [], default_model_id: null };
      if (path === "/api/v1/flows/ai-builder/sessions" && init?.method === "get") {
        return { sessions: [draft] };
      }
      if (path === "/api/v1/flows/ai-builder/sessions/{session_id}") return session;
      return {};
    }) as unknown as AIBuilderClientTransport["fetch"];
    render(FlowAIBuilderHarness, { transport: { fetch, stream: vi.fn() } });

    // Answered question shows the chosen answer inline.
    expect(await screen.findByText("— Avsnitt per källa")).toBeTruthy();

    // The superseded interpretation is collapsed; only the latest is expanded.
    expect(screen.getByText("Andra tolkningen.")).toBeTruthy();
    expect(screen.queryByText("Första tolkningen.")).toBeNull();
    expect(screen.getByText(m.ai_builder_requirements_superseded())).toBeTruthy();
  });
});

describe("FlowAIBuilder generation wait state", () => {
  it("keeps the composer editable as a saved draft while generation streams", async () => {
    const draft = {
      session_id: "gen-session",
      space_id: "space-1",
      status: "chatting",
      target_kind: "create",
      flow_id: null,
      latest_plan_id: null,
      draft_title: "Nytt flöde",
      created_at: "2026-07-12T09:00:00Z",
      updated_at: "2026-07-12T09:00:00Z"
    };
    const session = {
      ...draft,
      conversation: [
        {
          message_id: "u1",
          role: "user",
          content: "Bygg ett flöde",
          timestamp: "2026-07-12T09:00:00Z"
        }
      ],
      latest_turn: null
    };
    const fetch = vi.fn(async (path: string, init?: { method?: string }) => {
      if (path.endsWith("/models")) return { models: [], default_model_id: null };
      if (path === "/api/v1/flows/ai-builder/sessions" && init?.method === "get") {
        return { sessions: [draft] };
      }
      if (path === "/api/v1/flows/ai-builder/sessions/{session_id}") return session;
      return {};
    }) as unknown as AIBuilderClientTransport["fetch"];
    // Emits a real backend phase, then stays open — the wait state persists.
    const stream = vi.fn(async (_path, _init, handlers) => {
      handlers.onMessage({
        event: "status",
        data: JSON.stringify({ status: "architecture_committed" })
      });
      await new Promise(() => {});
    }) as AIBuilderClientTransport["stream"];

    render(FlowAIBuilderHarness, { transport: { fetch, stream } });

    const textbox = (await screen.findByRole("textbox")) as HTMLTextAreaElement;
    await fireEvent.input(textbox, { target: { value: "Bygg ett flöde" } });
    await fireEvent.keyDown(textbox, { key: "Enter" });

    // The wait state is showing and the composer promises only what is true:
    // typing works (draft persists), sending waits for the turn to finish.
    expect(await screen.findByText(m.ai_builder_wait_expectation())).toBeTruthy();
    expect(screen.getByText(m.ai_builder_wait_composer_hint())).toBeTruthy();
    expect(textbox.disabled).toBe(false);
    await fireEvent.input(textbox, { target: { value: "Ta med en summering" } });
    expect(JSON.parse(localStorage.getItem("eneo:ai-builder:draft:gen-session") ?? "{}").text).toBe(
      "Ta med en summering"
    );
    expect(
      (screen.getByRole("button", { name: m.ai_builder_send() }) as HTMLButtonElement).disabled
    ).toBe(true);
  });
});

describe("FlowAIBuilder generation failure (E1)", () => {
  it("keeps the plan pane, shows E1 once and suppresses the chat banner", async () => {
    const draft = {
      session_id: "gen-session",
      space_id: "space-1",
      status: "chatting",
      target_kind: "create",
      flow_id: null,
      latest_plan_id: null,
      draft_title: "Nytt flöde",
      created_at: "2026-07-12T09:00:00Z",
      updated_at: "2026-07-12T09:00:00Z"
    };
    const session = {
      ...draft,
      conversation: [
        {
          message_id: "u1",
          role: "user",
          content: "Bygg ett flöde",
          timestamp: "2026-07-12T09:00:00Z"
        }
      ],
      latest_turn: null
    };
    const fetch = vi.fn(async (path: string, init?: { method?: string }) => {
      if (path.endsWith("/models")) return { models: [], default_model_id: null };
      if (path === "/api/v1/flows/ai-builder/sessions" && init?.method === "get") {
        return { sessions: [draft] };
      }
      if (path === "/api/v1/flows/ai-builder/sessions/{session_id}") return session;
      return {};
    }) as unknown as AIBuilderClientTransport["fetch"];
    const publicError = JSON.stringify({
      schema_version: 2,
      code: "internal_error",
      category: "internal",
      message: "planner exploded mid-generation",
      phase: "planner",
      request_id: null,
      diagnostic_context: null,
      details: {}
    });
    const stream = vi.fn(async (_path, _init, handlers) => {
      handlers.onMessage({
        event: "status",
        data: JSON.stringify({ status: "architecture_committed" })
      });
      // Let the shell's generation latch observe the wait state, as it would
      // between real SSE frames.
      await new Promise((resolve) => setTimeout(resolve, 0));
      handlers.onMessage({ event: "error", data: publicError });
      handlers.onMessage({ event: "done", data: "" });
      handlers.onClose();
    }) as AIBuilderClientTransport["stream"];

    render(FlowAIBuilderHarness, { transport: { fetch, stream } });

    const textbox = (await screen.findByRole("textbox")) as HTMLTextAreaElement;
    await fireEvent.input(textbox, { target: { value: "Bygg ett flöde" } });
    await fireEvent.keyDown(textbox, { key: "Enter" });

    // E1 owns the failure: pane stays, banner renders once, and the chat's
    // destructive alert (which would carry the raw error message) is gone.
    expect(await screen.findByText(m.ai_builder_generation_failed_title())).toBeTruthy();
    expect(screen.getAllByText(m.ai_builder_generation_failed_title())).toHaveLength(1);
    expect(screen.getByRole("button", { name: m.ai_builder_show_conversation() })).toBeTruthy();
    expect(screen.queryByText("planner exploded mid-generation")).toBeNull();
  });
});

describe("FlowAIBuilder", () => {
  it("keeps model loading visible and recovers in place after a failed first request", async () => {
    localStorage.setItem("eneo:flow-user-mode", "power_user");
    const modelId = "11111111-1111-4111-8111-111111111113";
    const session = {
      session_id: "model-session",
      space_id: "space-1",
      status: "chatting" as const,
      target_kind: "create" as const,
      flow_id: null,
      latest_plan_id: null,
      conversation: []
    };
    let rejectInitialModelRequest!: (reason: Error) => void;
    const initialModelRequest = new Promise<never>((_resolve, reject) => {
      rejectInitialModelRequest = reject;
    });
    let modelRequestCount = 0;
    function makeTransport(): AIBuilderClientTransport {
      const fetch = vi.fn();
      fetch.mockImplementation(async (path: string, init?: { method?: string }) => {
        if (path.endsWith("/models")) {
          modelRequestCount += 1;
          if (modelRequestCount === 1) return await initialModelRequest;
          return {
            models: [{ id: modelId, name: "GPT-5.4", provider: "openai" }],
            default_model_id: modelId
          };
        }
        if (path === "/api/v1/flows/ai-builder/sessions" && init?.method === "post") {
          return session;
        }
        if (path === "/api/v1/flows/ai-builder/sessions/{session_id}") {
          return session;
        }
        if (path === "/api/v1/flows/ai-builder/sessions" && init?.method === "get") {
          return { sessions: [] };
        }
        throw new Error(`Unexpected request: ${path}`);
      });
      return { fetch, stream: vi.fn() };
    }

    render(FlowAIBuilderHarness, { transport: makeTransport() });

    const loading = await screen.findByRole("status");
    expect(loading.textContent).toContain(m.loading());
    expect(loading.getAttribute("aria-busy")).toBe("true");
    rejectInitialModelRequest(new Error("model endpoint unavailable"));
    expect((await screen.findByRole("alert")).textContent).toContain(m.failed_to_load_models());

    await fireEvent.click(screen.getByRole("button", { name: m.retry() }));

    expect(
      await screen.findByRole("button", {
        name: `${m.ai_builder_model_label()}: GPT-5.4`
      })
    ).toBeTruthy();
    expect(screen.queryByText(m.failed_to_load_models())).toBeNull();
    expect(modelRequestCount).toBe(2);
  });

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
