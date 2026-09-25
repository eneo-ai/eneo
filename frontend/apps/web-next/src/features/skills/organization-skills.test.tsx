// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { OrganizationSkill } from "./organization-skills";
import { removalRequest, selectedSkills, serverBlockingIds } from "./organization-skills";
import { deriveSkillSlug, normalizedSkillContent } from "./skill-model";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
const push = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get, POST: post } }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams()
}));
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useLocale: () => "en"
}));

import { OrganizationSkillsPage } from "./organization-skills-page";
import { OrganizationSkillNewPage } from "./organization-skill-new-page";

const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });
const usage = {
  assistant_count: 0,
  app_count: 0,
  distinct_space_count: 0,
  personal_chat_pinned: false
};
const skill = {
  id: "skill-1",
  display_name: "Search reports",
  description: "Search the report catalogue",
  slug: "search-reports",
  current_revision_number: 1,
  updated_at: "2026-09-01T12:00:00Z",
  publication_state: "draft",
  execution_blocked: false,
  removed_at: null,
  usage
} as OrganizationSkill;

beforeEach(() => {
  get.mockImplementation(() => ok({ items: [skill], next_cursor: null }));
  post.mockImplementation(() =>
    ok({
      removed_ids: [skill.id],
      detached: { assistant_count: 0, app_count: 0, personal_chat_count: 0 }
    })
  );
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function show(page: "list" | "new") {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      {page === "list" ? <OrganizationSkillsPage /> : <OrganizationSkillNewPage />}
    </QueryClientProvider>
  );
}

describe("organisation skill catalogue", () => {
  it("sends search terms as a query and requests the removed view separately", async () => {
    show("list");
    await screen.findByText("Search reports");
    // A tab of the organization space, whose header holds the page's h1.
    expect(screen.getByRole("heading", { level: 2, name: "skills" })).toBeTruthy();
    expect(screen.queryByRole("heading", { level: 1 })).toBeNull();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Reports" } });
    fireEvent.submit(screen.getByRole("search"));
    expect(push).toHaveBeenCalledWith("/spaces/organization/skills?search=Reports");
    fireEvent.click(screen.getByRole("button", { name: "organization_skills_removed_filter" }));
    expect(push).toHaveBeenCalledWith("/spaces/organization/skills?removed=true");
  });

  it("removes selected unbound skills without detachment approval", async () => {
    show("list");
    await screen.findByText("Search reports");
    fireEvent.click(screen.getByRole("checkbox", { name: "organization_skills_select_skill" }));
    fireEvent.click(screen.getByRole("button", { name: "organization_skills_remove_selected" }));
    const dialog = screen.getByRole("alertdialog");
    fireEvent.click(
      within(dialog).getByRole("button", { name: "organization_skills_remove_action" })
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/skills/organization/remove/", {
        body: { skill_ids: ["skill-1"], detach_bindings: false }
      })
    );
  });

  it("requires explicit detachment when an existing binding is shown", async () => {
    get.mockImplementation(() =>
      ok({ items: [{ ...skill, usage: { ...usage, assistant_count: 1 } }], next_cursor: null })
    );
    show("list");
    await screen.findByText("Search reports");
    fireEvent.click(screen.getByRole("button", { name: "organization_skills_remove_aria" }));
    const dialog = screen.getByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("checkbox"));
    expect(
      within(dialog)
        .getByRole("button", { name: "organization_skills_remove_action" })
        .hasAttribute("disabled")
    ).toBe(true);
    fireEvent.click(within(dialog).getByRole("checkbox"));
    fireEvent.click(
      within(dialog).getByRole("button", { name: "organization_skills_remove_action" })
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/skills/organization/remove/", {
        body: { skill_ids: ["skill-1"], detach_bindings: true }
      })
    );
  });

  it("creates a draft with trimmed content and an identifier derived from the name", async () => {
    post.mockImplementation(() => ok({ id: "created" }));
    show("new");
    fireEvent.change(screen.getByLabelText("skills_display_name_label"), {
      target: { value: "Résumé Search" }
    });
    fireEvent.change(screen.getByLabelText("skills_description_label"), {
      target: { value: " Search reports " }
    });
    fireEvent.change(screen.getByLabelText("skills_instructions_label"), {
      target: { value: " Use the index " }
    });
    fireEvent.click(screen.getByRole("button", { name: "skills_create_action" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/skills/organization/", {
        body: {
          display_name: "Résumé Search",
          description: "Search reports",
          instructions: "Use the index",
          slug: "resume-search"
        }
      })
    );
    await waitFor(() => expect(push).toHaveBeenCalledWith("/spaces/organization/skills/created"));
  });
});

describe("skill contracts", () => {
  it("preserves the old slug normalization and trims only submitted content", () => {
    expect(deriveSkillSlug(" Återkoppling & Metrics! ")).toBe("aterkoppling-metrics");
    expect(
      normalizedSkillContent({
        display_name: " Skill ",
        description: " Body ",
        instructions: " Steps "
      })
    ).toEqual({ display_name: "Skill", description: "Body", instructions: "Steps" });
  });

  it("keeps selection bounded and requires detachment for server-discovered bindings", () => {
    expect(selectedSkills([skill], [skill.id])).toEqual([skill]);
    expect(removalRequest([skill], false, [skill.id])).toBeNull();
    expect(removalRequest([skill], true, [skill.id])).toEqual({
      skill_ids: [skill.id],
      detach_bindings: true
    });
    expect(serverBlockingIds({ skill_ids: ["x", 7] })).toEqual(["x"]);
  });
});
