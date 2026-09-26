// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get, POST: post } }));
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useLocale: () => "en"
}));

import { OrganizationSkillDetailPage } from "./organization-skill-detail-page";
import { OrganizationSkillExecution } from "./organization-skill-execution";
import { OrganizationSkillPublication } from "./organization-skill-publication";

const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });
const currentRevision = {
  id: "rev-2",
  skill_id: "skill-1",
  revision_number: 2,
  display_name: "Reports",
  description: "Report search",
  instructions: "Search carefully",
  created_at: "2026-09-01T12:00:00Z"
};
const olderRevision = {
  ...currentRevision,
  id: "rev-1",
  revision_number: 1,
  instructions: "Search fast"
};
const skill = {
  id: "skill-1",
  display_name: "Reports",
  description: "Report search",
  slug: "reports",
  current_revision_id: "rev-2",
  current_revision_number: 2,
  current_revision: currentRevision,
  publication_state: "draft",
  published_revision_number: null,
  first_published_at: null,
  execution_blocked: false,
  removed_at: null,
  usage: { assistant_count: 0, app_count: 0, distinct_space_count: 0, personal_chat_pinned: false }
} as Schema<"OrganizationSkillPublic">;

beforeEach(() => {
  get.mockImplementation((path: string) => {
    if (path === "/api/v1/skills/organization/{skill_id}/") return ok(skill);
    if (path.endsWith("/revisions/"))
      return ok({ items: [currentRevision, olderRevision], next_cursor: null });
    if (path.endsWith("/revisions/{revision_id}/")) return ok(olderRevision);
    if (path.endsWith("/adoption/")) return ok({ summary: null, items: [], next_cursor: null });
    if (path.includes("execution-block")) return ok({ skill_id: skill.id, block: null });
    return ok({});
  });
  post.mockImplementation(() => ok(currentRevision));
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function show(node: React.ReactNode) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}

describe("organisation skill detail", () => {
  it("saves a changed content version through the revision endpoint", async () => {
    show(<OrganizationSkillDetailPage skillId="skill-1" />);
    await screen.findByLabelText("skills_instructions_label");
    fireEvent.change(screen.getByLabelText("skills_instructions_label"), {
      target: { value: " Search the archive " }
    });
    fireEvent.click(screen.getByRole("button", { name: "save_changes" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/skills/organization/{skill_id}/revisions/", {
        params: { path: { skill_id: "skill-1" } },
        body: {
          display_name: "Reports",
          description: "Report search",
          instructions: "Search the archive"
        }
      })
    );
  });

  it("restores an older version only after confirming the current revision identity", async () => {
    post.mockImplementation(() =>
      ok({
        revision: { ...olderRevision, id: "rev-3", revision_number: 3 },
        created: true,
        restored_from_revision_number: 1
      })
    );
    show(<OrganizationSkillDetailPage skillId="skill-1" />);
    const viewButtons = await screen.findAllByRole("button", {
      name: "skills_library_view_revision_aria"
    });
    fireEvent.click(viewButtons[1]!);
    await screen.findByText("Search fast");
    fireEvent.click(
      screen.getByRole("button", { name: "skills_library_restore_revision_from_preview" })
    );
    const dialog = screen.getByRole("alertdialog");
    fireEvent.click(within(dialog).getByRole("button", { name: "skills_library_restore_action" }));
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/v1/skills/organization/{skill_id}/revisions/{source_revision_id}/restore/",
        {
          params: { path: { skill_id: "skill-1", source_revision_id: "rev-1" } },
          body: { reviewed_current_revision_id: "rev-2" }
        }
      )
    );
  });

  it("publishes the exact reviewed revision and respects opt-outs for binding updates", async () => {
    post.mockImplementation(() =>
      ok({ ...skill, publication_state: "published", published_revision_number: 2 })
    );
    show(<OrganizationSkillPublication skill={skill} unsaved={false} />);
    fireEvent.click(screen.getByRole("button", { name: "organization_skills_publish_action" }));
    const dialog = screen.getByRole("alertdialog");
    for (const checkbox of within(dialog).getAllByRole("checkbox")) fireEvent.click(checkbox);
    fireEvent.click(
      within(dialog).getByRole("button", { name: "organization_skills_publish_action" })
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/skills/organization/{skill_id}/publish/", {
        params: { path: { skill_id: "skill-1" } },
        body: { expected_revision_id: "rev-2" }
      })
    );
    expect(post).toHaveBeenCalledTimes(1);
  });

  it("shows a missing reason at the field, which takes focus, before blocking", async () => {
    show(<OrganizationSkillExecution skillId="skill-1" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "organization_skills_execution_block_action" })
    );
    const dialog = screen.getByRole("alertdialog");
    const confirm = within(dialog).getByRole("button", {
      name: "organization_skills_execution_block_confirm"
    });
    // Never disabled: a disabled button says nothing about what is missing.
    expect((confirm as HTMLButtonElement).disabled).toBe(false);

    fireEvent.click(confirm);

    const reason = screen.getByLabelText("organization_skills_execution_reason_label");
    expect(reason.getAttribute("aria-invalid")).toBe("true");
    expect(reason.getAttribute("aria-describedby")).toContain("execution-change-reason-hint");
    expect(document.activeElement).toBe(reason);
    expect(post).not.toHaveBeenCalled();
  });

  it("records a reason and the reviewed block id when unblocking", async () => {
    const block = { id: "block-1", reason: "Incident", blocked_at: "2026-09-01T12:00:00Z" };
    post.mockImplementation((path: string) =>
      ok({ skill_id: skill.id, block: path.endsWith("/unblock") ? null : block })
    );
    show(<OrganizationSkillExecution skillId="skill-1" />);
    fireEvent.click(
      await screen.findByRole("button", { name: "organization_skills_execution_block_action" })
    );
    fireEvent.change(screen.getByLabelText("organization_skills_execution_reason_label"), {
      target: { value: " Incident " }
    });
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "organization_skills_execution_block_confirm"
      })
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/settings/skills/{skill_id}/execution-block", {
        params: { path: { skill_id: "skill-1" } },
        body: { reason: "Incident" }
      })
    );
    fireEvent.click(
      await screen.findByRole("button", { name: "organization_skills_execution_unblock_action" })
    );
    fireEvent.change(screen.getByLabelText("organization_skills_execution_reason_label"), {
      target: { value: "Resolved" }
    });
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "organization_skills_execution_unblock_confirm"
      })
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/v1/settings/skills/{skill_id}/execution-block/unblock",
        {
          params: { path: { skill_id: "skill-1" } },
          body: { reason: "Resolved", expected_block_id: "block-1" }
        }
      )
    );
  });
});
