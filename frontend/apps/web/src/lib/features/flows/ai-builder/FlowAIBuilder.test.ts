// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/svelte";
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
});
