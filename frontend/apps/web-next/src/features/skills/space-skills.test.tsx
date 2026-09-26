// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const patch = vi.hoisted(() => vi.fn());
const remove = vi.hoisted(() => vi.fn());
const push = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({
  browserApi: { GET: get, POST: post, PATCH: patch, DELETE: remove }
}));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({
    space: { id: "space-1", skill_permissions: ["read", "create", "edit", "delete"] },
    routeId: "space-1",
    can: () => true
  })
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push }) }));
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useLocale: () => "en"
}));

import { SpaceSkillsPage } from "./space-skills-page";
import { SpaceSkillNewPage } from "./space-skill-new-page";
import { SpaceSkillDetailPage } from "./space-skill-detail-page";

const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });
const revision = {
  id: "rev-2",
  skill_id: "skill-1",
  revision_number: 2,
  display_name: "Reports",
  description: "Find reports",
  instructions: "Search",
  created_at: "2026-09-01T12:00:00Z"
};
const older = { ...revision, id: "rev-1", revision_number: 1, instructions: "Browse" };
const skill = {
  id: "skill-1",
  space_id: "space-1",
  slug: "reports",
  is_active: true,
  display_name: "Reports",
  description: "Find reports",
  current_revision_id: "rev-2",
  current_revision_number: 2,
  updated_at: "2026-09-01T12:00:00Z",
  current_revision: revision
};

beforeEach(() => {
  get.mockImplementation((path: string) => {
    if (path === "/api/v1/spaces/{space_id}/skills/")
      return ok({ items: [skill], next_cursor: null });
    if (path === "/api/v1/spaces/{space_id}/skills/{skill_id}/") return ok(skill);
    if (path.endsWith("/revisions/")) return ok({ items: [revision, older], next_cursor: null });
    if (path.endsWith("/revisions/{revision_id}/")) return ok(older);
    return ok({});
  });
  post.mockImplementation(() => ok(skill));
  patch.mockImplementation(() => ok({ ...skill, is_active: false }));
  remove.mockImplementation(() => ok(undefined));
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function show(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe("space Skills", () => {
  it("loads a bounded catalogue page, searches with q and confirms deletion", async () => {
    show(<SpaceSkillsPage />);
    await screen.findByText("Reports");
    // Named like the page heading (translation keys stand in for the text here).
    expect(screen.getByRole("table", { name: "skills" })).toBeTruthy();
    expect(get).toHaveBeenCalledWith("/api/v1/spaces/{space_id}/skills/", {
      params: { path: { space_id: "space-1" }, query: { limit: 25, cursor: null, q: undefined } }
    });
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "reports" } });
    fireEvent.submit(screen.getByRole("search"));
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/api/v1/spaces/{space_id}/skills/", {
        params: { path: { space_id: "space-1" }, query: { limit: 25, cursor: null, q: "reports" } }
      })
    );
    await screen.findByText("Reports");
    fireEvent.click(screen.getByRole("button", { name: "skills_library_delete_aria" }));
    expect(remove).not.toHaveBeenCalled();
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "delete" })
    );
    await waitFor(() =>
      expect(remove).toHaveBeenCalledWith("/api/v1/spaces/{space_id}/skills/{skill_id}/", {
        params: { path: { space_id: "space-1", skill_id: "skill-1" } }
      })
    );
  });

  it("moves focus to the heading when the deleted skill's row goes away", async () => {
    remove.mockImplementation(() => {
      get.mockImplementation(() => ok({ items: [], next_cursor: null }));
      return ok(undefined);
    });
    show(<SpaceSkillsPage />);
    const trigger = await screen.findByRole("button", { name: "skills_library_delete_aria" });
    trigger.focus();
    fireEvent.click(trigger);
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", { name: "delete" })
    );

    await screen.findByRole("heading", { level: 3, name: "skills_library_empty_title" });
    await waitFor(() =>
      expect(document.activeElement).toBe(screen.getByRole("heading", { level: 2, name: "skills" }))
    );
    expect(screen.getByText("skills_library_deleted_success").getAttribute("role")).toBe("status");
  });

  it("keeps focus on a busy delete and deletes once", async () => {
    remove.mockReturnValue(new Promise(() => {}));
    show(<SpaceSkillsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "skills_library_delete_aria" }));
    const dialog = screen.getByRole("alertdialog");
    const confirm = within(dialog).getByRole("button", { name: "delete" });
    confirm.focus();

    fireEvent.click(confirm);

    const busy = await within(dialog).findByRole("button", { name: "skills_library_deleting" });
    expect(busy).toBe(confirm);
    expect(busy.getAttribute("aria-busy")).toBe("true");
    expect(busy.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(busy);
    fireEvent.click(busy);
    expect(remove).toHaveBeenCalledTimes(1);
  });

  it("keeps a failed delete's error in the dialog", async () => {
    remove.mockImplementation(() => Promise.reject(new Error("offline")));
    show(<SpaceSkillsPage />);
    fireEvent.click(await screen.findByRole("button", { name: "skills_library_delete_aria" }));
    const dialog = screen.getByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "delete" }));
    const alert = await within(dialog).findByRole("alert");
    expect(within(alert).getAllByText("request_failed").length).toBeGreaterThan(0);
  });

  it("creates a Skill in the current space using the shared form", async () => {
    show(<SpaceSkillNewPage />);
    // The sticky footer never covers a focused field: the fields keep a
    // bottom scroll margin as tall as the footer.
    expect(
      screen.getByLabelText("skills_display_name_label").closest(".\\[\\&_\\*\\]\\:scroll-mb-20")
    ).toBeTruthy();
    fireEvent.change(screen.getByLabelText("skills_display_name_label"), {
      target: { value: "Reports" }
    });
    fireEvent.change(screen.getByLabelText("skills_description_label"), {
      target: { value: "Find reports" }
    });
    fireEvent.change(screen.getByLabelText("skills_instructions_label"), {
      target: { value: "Search" }
    });
    fireEvent.click(screen.getByRole("button", { name: "skills_create_action" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/spaces/{space_id}/skills/", {
        params: { path: { space_id: "space-1" } },
        body: {
          display_name: "Reports",
          description: "Find reports",
          instructions: "Search",
          slug: "reports"
        }
      })
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/spaces/space-1/skills/skill-1"));
  });

  it("changes availability and saves a new immutable revision", async () => {
    show(<SpaceSkillDetailPage skillId="skill-1" />);
    fireEvent.click(
      await screen.findByRole("switch", { name: "skills_library_availability_switch_label" })
    );
    await waitFor(() =>
      expect(patch).toHaveBeenCalledWith("/api/v1/spaces/{space_id}/skills/{skill_id}/active/", {
        params: { path: { space_id: "space-1", skill_id: "skill-1" } },
        body: { is_active: false }
      })
    );
    fireEvent.change(screen.getByLabelText("skills_instructions_label"), {
      target: { value: "Search the archive" }
    });
    fireEvent.click(screen.getByRole("button", { name: "save_changes" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/", {
        params: { path: { space_id: "space-1", skill_id: "skill-1" } },
        body: {
          display_name: "Reports",
          description: "Find reports",
          instructions: "Search the archive"
        }
      })
    );
  });

  it("restores a reviewed space version using the shared history", async () => {
    post.mockImplementation(() =>
      ok({
        revision: { ...older, id: "rev-3", revision_number: 3 },
        created: true,
        restored_from_revision_number: 1
      })
    );
    show(<SpaceSkillDetailPage skillId="skill-1" />);
    const buttons = await screen.findAllByRole("button", {
      name: "skills_library_view_revision_aria"
    });
    fireEvent.click(buttons[1]!);
    await screen.findByText("Browse");
    fireEvent.click(
      screen.getByRole("button", { name: "skills_library_restore_revision_from_preview" })
    );
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "skills_library_restore_action"
      })
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/v1/spaces/{space_id}/skills/{skill_id}/revisions/{source_revision_id}/restore/",
        {
          params: {
            path: { space_id: "space-1", skill_id: "skill-1", source_revision_id: "rev-1" }
          },
          body: { reviewed_current_revision_id: "rev-2" }
        }
      )
    );
  });
});
