// @vitest-environment jsdom
import { cleanup, fireEvent, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { awaitPartnerUpdates } from "@/features/chat/partner-updates";
import type { Schema } from "@/lib/api/models";
import { renderInApp, testAppContext } from "@/test/render";
import { SpaceSkillDetailPage } from "./space-skill-detail-page";
import { SpaceSkillsPage } from "./space-skills-page";

type Summary = Schema<"AssistantSkillBindingSummary">;

const api = vi.hoisted(() => ({ GET: vi.fn(), POST: vi.fn(), PATCH: vi.fn(), DELETE: vi.fn() }));
vi.mock("@/lib/api/browser", () => ({ browserApi: api }));
vi.mock("next/navigation", () => import("@/test/navigation"));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    space: {
      id: "personal-space",
      personal: true,
      default_assistant: { id: "assistant-1", completion_model: { id: "model-1" } }
    },
    routeId: "personal",
    can: () => true
  })
}));

const ok = (data: unknown) => Promise.resolve({ data, response: new Response("{}") });

function skill(id: string, name: string) {
  const revision = {
    id: `${id}-r3`,
    skill_id: id,
    revision_number: 3,
    display_name: name,
    description: "Korta svar",
    instructions: "Svara kort.",
    created_at: "2026-10-01T08:00:00Z"
  };
  return {
    id,
    space_id: "personal-space",
    slug: id,
    is_active: true,
    current_revision_id: revision.id,
    current_revision_number: 3,
    display_name: name,
    description: "Korta svar",
    content_digest: "digest",
    created_by_user_id: "user-1",
    created_at: "2026-10-01T08:00:00Z",
    updated_at: "2026-10-01T08:00:00Z",
    current_revision: revision
  };
}

const answers = skill("answers", "Mina svarspreferenser");
const notes = skill("notes", "Mötesanteckningar");
/** The chat pins version 1 of "answers"; version 3 is the latest. */
const binding: Summary = {
  skill_id: "answers",
  skill_revision_id: "answers-r1",
  attachable_revision_id: "answers-r3",
  slug: "answers",
  revision_number: 1,
  attachable_revision_number: 3,
  display_name: "Mina svarspreferenser",
  description: "Korta svar",
  content_digest: "digest",
  position: 0,
  is_active: true,
  source: "space",
  execution_blocked: false,
  activation_mode: "always"
};
let bindings: Summary[];

beforeEach(() => {
  bindings = [binding];
  api.GET.mockImplementation(
    (path: string, init?: { params?: { path?: { skill_id?: string } } }) => {
      if (path === "/api/v1/spaces/{space_id}/assistants/{assistant_id}/skills/configuration/")
        return ok({
          bindings,
          organisation_bindings: [],
          personal_layer: { status: "applied", reason: null, detail: null },
          runtime: null
        });
      if (path === "/api/v1/spaces/{space_id}/skills/")
        return ok({ items: [answers, notes], total_count: 2, next_cursor: null });
      if (path === "/api/v1/spaces/{space_id}/skills/{skill_id}/")
        return ok(init?.params?.path?.skill_id === "notes" ? notes : answers);
      if (path === "/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/")
        return ok({ items: [answers.current_revision], total_count: 1, next_cursor: null });
      throw new Error(`Unexpected GET ${path}`);
    }
  );
  api.POST.mockImplementation(() => {
    bindings = [{ ...binding, skill_revision_id: "answers-r3", revision_number: 3 }];
    return ok({});
  });
});

afterEach(async () => {
  cleanup();
  await awaitPartnerUpdates();
  vi.clearAllMocks();
});

const appContext = () => testAppContext({ permissions: ["personal_chat", "personal_skills"] });

describe("the personal chat on the personal space's Skills pages", () => {
  it("marks each skill the personal chat uses with its mode in the list", async () => {
    renderInApp(<SpaceSkillsPage />, { appContext: appContext() });

    // Under the name, whose column keeps room for the whole badge.
    const answersName = (
      await screen.findByRole("link", { name: "Mina svarspreferenser" })
    ).closest("td")!;
    expect(await within(answersName).findByText("Personlig chatt · Alltid")).toBeTruthy();
    const notesRow = screen.getByRole("link", { name: "Mötesanteckningar" }).closest("tr")!;
    expect(within(notesRow).queryByText(/Personlig chatt/)).toBeNull();
  });

  it("says which version the chat uses and moves it to the latest on request", async () => {
    renderInApp(<SpaceSkillDetailPage skillId="answers" />, { appContext: appContext() });

    expect(await screen.findByText("Din personliga chatt använder version 1.")).toBeTruthy();
    const move = screen.getByRole("button", { name: "Använd senaste versionen" });
    move.focus();
    fireEvent.click(move);

    await waitFor(() =>
      expect(api.POST).toHaveBeenCalledWith("/api/v1/assistants/{id}/", {
        params: { path: { id: "assistant-1" } },
        body: {
          skill_bindings: [
            { skill_id: "answers", skill_revision_id: "answers-r3", activation_mode: "always" }
          ]
        }
      })
    );
    await waitFor(() =>
      expect(screen.queryByText("Din personliga chatt använder version 1.")).toBeNull()
    );
    // The notice went with the button; focus is on the page heading, not lost.
    await waitFor(() =>
      expect(document.activeElement).toBe(
        screen.getByRole("heading", { level: 1, name: "Mina svarspreferenser" })
      )
    );
  });

  it("shows no notice for a skill the chat uses at its latest version, or not at all", async () => {
    renderInApp(<SpaceSkillDetailPage skillId="notes" />, { appContext: appContext() });
    await screen.findByRole("heading", { level: 1, name: "Mötesanteckningar" });
    await waitFor(() =>
      expect(api.GET).toHaveBeenCalledWith(
        "/api/v1/spaces/{space_id}/assistants/{assistant_id}/skills/configuration/",
        expect.anything()
      )
    );
    await waitFor(() => expect(screen.queryByText(/Laddar/)).toBeNull());
    expect(screen.queryByText(/Din personliga chatt använder/)).toBeNull();
  });
});
