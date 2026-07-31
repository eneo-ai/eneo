import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import type { RecoverableAIBuilderDraftSession } from "$lib/features/flows/ai-builder/protocol";
import FlowDraftsResumeStrip from "./FlowDraftsResumeStrip.svelte";

afterEach(() => {
  cleanup();
});

function makeDraft(
  overrides: Partial<RecoverableAIBuilderDraftSession> = {}
): RecoverableAIBuilderDraftSession {
  return {
    session_id: "draft-1",
    space_id: "space-1",
    status: "awaiting_approval",
    target_kind: "create",
    flow_id: null,
    latest_plan_id: "plan-1",
    draft_title: "Sammanfatta till PDF",
    created_at: "2026-07-13T08:00:00Z",
    updated_at: "2026-07-13T08:05:00Z",
    ...overrides
  } as RecoverableAIBuilderDraftSession;
}

describe("FlowDraftsResumeStrip", () => {
  it("renders nothing when there are no drafts", () => {
    const { container } = render(FlowDraftsResumeStrip, { drafts: [], spaceRouteId: "personal" });
    expect(container.querySelector("a")).toBeNull();
  });

  it("links to the builder with count, titles, and untitled fallback", () => {
    render(FlowDraftsResumeStrip, {
      drafts: [makeDraft(), makeDraft({ session_id: "draft-2", draft_title: null })],
      spaceRouteId: "personal"
    });

    const strip = screen.getByRole("link");
    expect(strip.getAttribute("href")).toMatch(/\/spaces\/personal\/flows\/ai-builder$/);
    expect(strip.textContent).toContain("Pågående AI-utkast (2)");
    expect(strip.textContent).toContain("Sammanfatta till PDF");
    expect(strip.textContent).toContain("Namnlöst utkast");
    expect(strip.textContent).toContain("Fortsätt där du slutade");
  });

  it("previews at most three titles and marks the overflow", () => {
    render(FlowDraftsResumeStrip, {
      drafts: [
        makeDraft({ session_id: "a", draft_title: "Alpha" }),
        makeDraft({ session_id: "b", draft_title: "Beta" }),
        makeDraft({ session_id: "c", draft_title: "Gamma" }),
        makeDraft({ session_id: "d", draft_title: "Delta" })
      ],
      spaceRouteId: "personal"
    });

    const strip = screen.getByRole("link");
    expect(strip.textContent).toContain("Alpha · Beta · Gamma …");
    expect(strip.textContent).not.toContain("Delta");
  });
});
