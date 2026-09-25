// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get, POST: post } }));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

import { OrganizationSkillAdoption } from "./organization-skill-adoption";

const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });
const failed = (code = 500) =>
  Promise.resolve({
    error: { message: "Service failed" },
    response: new Response("{}", { status: code })
  });
const skill = {
  id: "skill-1",
  current_revision_id: "rev-2",
  current_revision_number: 2,
  published_revision_number: 2,
  publication_state: "published",
  execution_blocked: false
} as Schema<"OrganizationSkillPublic">;
const assistant = {
  kind: "assistant",
  resource_id: "assistant-1",
  name: "Research",
  space_id: "space-1",
  space_name: "Research",
  revision_id: "rev-1",
  revision_number: 1,
  drift: "behind",
  can_open: true
};
const app = {
  kind: "app",
  resource_id: "app-1",
  name: "Review app",
  space_id: "space-1",
  space_name: "Research",
  revision_id: "rev-1",
  revision_number: 1,
  drift: "behind",
  can_open: true
};
const page = {
  summary: {
    assistant_count: 1,
    app_count: 1,
    distinct_space_count: 1,
    behind_published_count: 2,
    personal_chat: { revision_id: "rev-1", revision_number: 1, drift: "behind" },
    revision_counts: [
      {
        revision_id: "rev-1",
        revision_number: 1,
        assistant_count: 1,
        app_count: 1,
        personal_chat_pinned: true
      }
    ]
  },
  items: [assistant, app],
  limit: 100,
  next_cursor: null,
  matched_count: 2
};

beforeEach(() => {
  get.mockImplementation((path: string) =>
    path.endsWith("/adoption/") ? ok(page) : ok({ revision_id: "rev-2" })
  );
  post.mockImplementation((path: string) =>
    path.endsWith("/detach/")
      ? ok({ assistant_count: 1, app_count: 1, personal_chat_count: 0 })
      : ok({
          counts: { advanced: 1, concurrent_change: 0, incompatible: 0 },
          outcomes: path.endsWith("/assistants/advance/")
            ? [{ assistant_id: "assistant-1" }]
            : [{ app_id: "app-1" }],
          next_cursor: null,
          to_revision_number: 2
        })
  );
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <OrganizationSkillAdoption skill={skill} />
    </QueryClientProvider>
  );
}

describe("organisation Skill bindings", () => {
  it("filters on the server and detaches only selected resources", async () => {
    show();
    await screen.findByText("Review app");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Review" } });
    fireEvent.submit(screen.getByRole("search"));
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/api/v1/skills/organization/{skill_id}/adoption/", {
        params: {
          path: { skill_id: "skill-1" },
          query: { limit: 100, cursor: null, query: "Review", kind: undefined, drift: undefined }
        }
      })
    );
    await screen.findByText("Review app");
    fireEvent.click(
      screen.getAllByRole("checkbox", { name: "organization_skills_adoption_select_resource" })[0]!
    );
    fireEvent.click(
      screen.getByRole("button", { name: "organization_skills_adoption_detach_selected" })
    );
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "organization_skills_adoption_detach_selected"
      })
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/skills/organization/{skill_id}/detach/", {
        params: { path: { skill_id: "skill-1" } },
        body: { assistant_ids: ["assistant-1"], app_ids: [] }
      })
    );
  });

  it("updates selected outdated bindings using the exact published revision", async () => {
    show();
    await screen.findByText("Review app");
    fireEvent.click(
      screen.getByRole("checkbox", { name: "organization_skills_adoption_select_shown" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "organization_skills_adoption_advance_selected" })
    );
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "organization_skills_adoption_advance_selected"
      })
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith(
        "/api/v1/skills/organization/{skill_id}/assistants/advance/",
        {
          params: { path: { skill_id: "skill-1" } },
          body: {
            expected_published_revision_id: "rev-2",
            cursor: null,
            assistant_ids: ["assistant-1"]
          }
        }
      )
    );
    expect(post).toHaveBeenCalledWith("/api/v1/skills/organization/{skill_id}/apps/advance/", {
      params: { path: { skill_id: "skill-1" } },
      body: { expected_published_revision_id: "rev-2", cursor: null, app_ids: ["app-1"] }
    });
  });

  it("retains failed app selection after assistants were committed", async () => {
    post.mockImplementation((path: string) =>
      path.endsWith("/apps/advance/")
        ? failed()
        : ok({
            counts: { advanced: 1, concurrent_change: 0, incompatible: 0 },
            outcomes: [{ assistant_id: "assistant-1" }],
            next_cursor: null
          })
    );
    show();
    await screen.findByText("Review app");
    fireEvent.click(
      screen.getByRole("checkbox", { name: "organization_skills_adoption_select_shown" })
    );
    fireEvent.click(
      screen.getByRole("button", { name: "organization_skills_adoption_advance_selected" })
    );
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "organization_skills_adoption_advance_selected"
      })
    );
    await screen.findByText(/organization_skills_adoption_advance_partial/);
    const rows = screen.getAllByRole("checkbox", {
      name: "organization_skills_adoption_select_resource"
    });
    expect((rows[0] as HTMLInputElement).checked).toBe(false);
    expect((rows[1] as HTMLInputElement).checked).toBe(true);
  });
});
