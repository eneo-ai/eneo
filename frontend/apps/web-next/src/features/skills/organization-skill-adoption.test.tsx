// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import type { Schema } from "@/lib/api/models";

const get = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get, POST: post } }));
vi.mock("use-intl", () => ({
  useTranslations: () => (key: string, values?: Record<string, string>) =>
    key === "organization_skills_adoption_resources_shown"
      ? `${key}:${values?.shown}/${values?.total}`
      : key
}));

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
  it("hides and resets drift when the Skill becomes unpublished", async () => {
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    const renderSkill = (value: typeof skill) => (
      <QueryClientProvider client={client}>
        <OrganizationSkillAdoption skill={value} />
      </QueryClientProvider>
    );
    const { rerender } = render(renderSkill(skill));
    await screen.findByText("Review app");
    fireEvent.change(screen.getByLabelText("organization_skills_adoption_filter_status_label"), {
      target: { value: "behind" }
    });
    await waitFor(() =>
      expect(get.mock.calls.some(([, options]) => options.params?.query?.drift === "behind")).toBe(
        true
      )
    );
    rerender(
      renderSkill({ ...skill, published_revision_number: null, publication_state: "draft" })
    );
    expect(screen.queryByLabelText("organization_skills_adoption_filter_status_label")).toBeNull();
    rerender(renderSkill(skill));
    expect(
      (
        screen.getByLabelText(
          "organization_skills_adoption_filter_status_label"
        ) as HTMLSelectElement
      ).value
    ).toBe("all");
  });

  it("explains adoption when no resource or personal chat uses the Skill", async () => {
    get.mockImplementation((path: string) =>
      path.endsWith("/adoption/")
        ? ok({
            ...page,
            items: [],
            summary: { ...page.summary, assistant_count: 0, app_count: 0, personal_chat: null }
          })
        : ok({ revision_id: "rev-2" })
    );
    show();
    expect(await screen.findByText("organization_skills_adoption_empty_title")).toBeTruthy();
    expect(screen.getByText("organization_skills_adoption_empty_description")).toBeTruthy();
  });
  it("shows personal-chat drift, revision pins and the server matched count", async () => {
    get.mockImplementation((path: string) =>
      path.endsWith("/adoption/")
        ? ok({ ...page, matched_count: 9, next_cursor: "more" })
        : ok({ revision_id: "rev-2" })
    );
    show();
    await screen.findByText("Review app");
    expect(screen.getByText(/organization_skills_adoption_pinned$/)).toBeTruthy();
    expect(screen.getAllByText("organization_skills_adoption_drift_behind").length).toBeGreaterThan(
      2
    );
    expect(screen.getByText("organization_skills_adoption_resources_shown:2/9")).toBeTruthy();
  });

  it("keeps an older search response out of the current live results", async () => {
    let resolveOld!: (value: unknown) => void;
    let oldSignal: AbortSignal | undefined;
    get.mockImplementation(
      (
        path: string,
        options: { signal?: AbortSignal; params?: { query?: { query?: string } } }
      ) => {
        if (!path.endsWith("/adoption/")) return ok({ revision_id: "rev-2" });
        if (options.params?.query?.query === "Old") {
          oldSignal = options.signal;
          return new Promise((resolve) => {
            resolveOld = resolve;
          });
        }
        if (options.params?.query?.query === "New")
          return ok({ ...page, items: [{ ...app, name: "New result" }] });
        return ok(page);
      }
    );
    show();
    await screen.findByText("Review app");
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Old" } });
    await waitFor(() => expect(resolveOld).toBeTypeOf("function"));
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "New" } });
    await screen.findByText("New result");
    expect(oldSignal?.aborted).toBe(true);
    await act(async () =>
      resolveOld({
        data: { ...page, items: [{ ...app, name: "Old result" }] },
        response: new Response("{}")
      })
    );
    expect(screen.queryByText("Old result")).toBeNull();
    expect(screen.getByText("New result")).toBeTruthy();
  });

  it("filters on the server and detaches only selected resources", async () => {
    show();
    await screen.findByText("Review app");
    // Named by its heading (translation keys stand in for the text).
    expect(
      screen.getByRole("table", { name: "organization_skills_adoption_resources_heading" })
    ).toBeTruthy();
    fireEvent.change(screen.getByRole("searchbox"), { target: { value: "Review" } });
    await waitFor(() =>
      expect(get).toHaveBeenCalledWith("/api/v1/skills/organization/{skill_id}/adoption/", {
        signal: expect.anything(),
        params: {
          path: { skill_id: "skill-1" },
          query: {
            limit: 100,
            cursor: undefined,
            query: "Review",
            kind: undefined,
            drift: undefined
          }
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

  it("keeps focus on a busy detach and detaches once", async () => {
    post.mockReturnValue(new Promise(() => {}));
    show();
    await screen.findByText("Review app");
    fireEvent.click(
      screen.getAllByRole("checkbox", { name: "organization_skills_adoption_select_resource" })[0]!
    );
    fireEvent.click(
      screen.getByRole("button", { name: "organization_skills_adoption_detach_selected" })
    );
    const dialog = screen.getByRole("alertdialog");
    const detach = within(dialog).getByRole("button", {
      name: "organization_skills_adoption_detach_selected"
    });
    detach.focus();

    fireEvent.click(detach);

    const busy = await within(dialog).findByRole("button", {
      name: "organization_skills_adoption_detaching"
    });
    expect(busy).toBe(detach);
    expect(busy.getAttribute("aria-busy")).toBe("true");
    expect(busy.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(busy);
    fireEvent.click(busy);
    expect(post).toHaveBeenCalledTimes(1);
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
