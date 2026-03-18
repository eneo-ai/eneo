// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowAIBuilderHarness from "./test-harnesses/FlowAIBuilderHarness.svelte";

afterEach(() => {
  cleanup();
});

describe("FlowAIBuilder", () => {
  it("shows create-draft recovery instead of auto-starting chat when a matching draft exists", async () => {
    const fetch = vi.fn().mockResolvedValueOnce({
      sessions: [
        {
          session_id: "draft-1",
          space_id: "space-1",
          status: "chatting",
          target_kind: "create",
          flow_id: null,
          latest_plan_id: null,
          draft_title: "Recovered draft",
          created_at: "2026-03-15T10:00:00Z",
          updated_at: "2026-03-15T10:05:00Z"
        }
      ]
    });

    render(FlowAIBuilderHarness, {
      transport: {
        fetch,
        stream: vi.fn()
      }
    });

    expect(await screen.findByText(m.ai_builder_recovery_title())).toBeInTheDocument();
    expect(screen.getByText("Recovered draft")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: m.ai_builder_resume_draft() })).toBeInTheDocument();
    expect(fetch).toHaveBeenCalledTimes(1);
  });
});
