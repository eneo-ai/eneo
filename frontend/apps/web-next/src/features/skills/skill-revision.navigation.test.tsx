// @vitest-environment jsdom
import { createBrowserHistory, createRoute } from "@tanstack/react-router";
import { act, fireEvent, screen, waitFor } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";
import { renderWithRouter } from "@/test/router";
import { OrganizationSkillDetailPage } from "./organization-skill-detail-page";

vi.unmock("@/lib/link");

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get, POST: post } }));

it("settles a pending Back when saving replaces the actual revision editor", async () => {
  const revision: Schema<"SkillRevisionPublic"> = {
    id: "revision-1",
    skill_id: "skill-1",
    revision_number: 1,
    display_name: "Reports",
    description: "Report search",
    instructions: "Search carefully",
    content_digest: "fixture",
    created_by_user_id: "user-1",
    created_at: "2026-09-01T12:00:00Z"
  };
  let skill: Schema<"OrganizationSkillPublic"> = {
    id: "skill-1",
    space_id: "space-1",
    slug: "reports",
    is_active: true,
    current_revision_id: revision.id,
    current_revision_number: 1,
    current_revision: revision,
    display_name: revision.display_name,
    description: revision.description,
    content_digest: revision.content_digest,
    created_by_user_id: revision.created_by_user_id,
    created_at: revision.created_at,
    updated_at: revision.created_at,
    publication_state: "draft",
    published_revision_number: null,
    first_published_at: null,
    execution_blocked: false,
    removed_at: null,
    usage: {
      assistant_count: 0,
      app_count: 0,
      distinct_space_count: 0,
      personal_chat_pinned: false
    }
  };
  const ok = (data: unknown) => ({ data, response: new Response() });
  get.mockImplementation(async (path: string) => {
    if (path === "/api/v1/skills/organization/{skill_id}/") return ok(skill);
    if (path.endsWith("/revisions/"))
      return ok({ items: [skill.current_revision], next_cursor: null });
    if (path.endsWith("/adoption/")) return ok({ summary: null, items: [], next_cursor: null });
    throw new Error(`Unexpected request: ${path}`);
  });
  let finish!: () => void;
  post.mockImplementation(
    () =>
      new Promise((resolve) => {
        finish = () => {
          const current = {
            ...revision,
            id: "revision-2",
            revision_number: 2,
            display_name: "Changed"
          };
          skill = {
            ...skill,
            display_name: current.display_name,
            current_revision_id: current.id,
            current_revision_number: 2,
            current_revision: current
          };
          resolve(ok(current));
        };
      })
  );
  window.history.replaceState(null, "", "/done");
  const history = createBrowserHistory();
  const { router, unmount } = await renderWithRouter(null, {
    history,
    routes: (root) => [
      createRoute({ getParentRoute: () => root, path: "/done", component: () => <h1>Done</h1> }),
      createRoute({
        getParentRoute: () => root,
        path: "/edit",
        component: () => <OrganizationSkillDetailPage skillId="skill-1" />
      })
    ]
  });
  try {
    await act(() => router.navigate({ href: "/edit" }));
    const input = await screen.findByRole("textbox", { name: "Namn" });
    fireEvent.change(input, { target: { value: "Changed" } });
    fireEvent.click(screen.getByRole("button", { name: "Spara ändringar" }));
    await waitFor(() => expect(post).toHaveBeenCalledTimes(1));
    await act(async () => router.history.back());
    await screen.findByRole("alertdialog");
    await act(async () => finish());
    await screen.findByRole("heading", { name: "Done" });
    expect(screen.queryByRole("alertdialog")).toBeNull();
    expect(router.state.location.pathname).toBe("/done");
    expect(window.location.pathname).toBe("/done");
    await act(async () => router.history.forward());
    await screen.findByRole("textbox", { name: "Namn" });
    expect(router.state.location.pathname).toBe("/edit");
    expect(window.location.pathname).toBe("/edit");
    expect((screen.getByRole("textbox", { name: "Namn" }) as HTMLInputElement).value).toBe(
      "Changed"
    );
    await act(async () => router.history.back());
    await screen.findByRole("heading", { name: "Done" });
  } finally {
    unmount();
    history.destroy();
  }
});
