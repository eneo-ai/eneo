// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get } }));
vi.mock("@/features/spaces/use-space", () => ({
  useSpace: () => ({ space: { id: "space", organization: false }, can: () => false })
}));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

import { SkillBindingsEditor, SkillBindingsSection } from "./skill-bindings-section";

const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });
const summary = (id: string, position: number) => ({
  skill_id: id,
  skill_revision_id: `revision-${id}`,
  attachable_revision_id: `revision-${id}`,
  attachable_revision_number: 1,
  revision_number: 1,
  display_name: `Skill ${id}`,
  description: `Description ${id}`,
  slug: id,
  source: "space" as const,
  position,
  is_active: true,
  execution_blocked: false,
  activation_mode: "always" as const,
  content_digest: "digest"
});

beforeEach(() => get.mockReset());
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function show(resource: "assistant" | "app", save: (bindings: unknown) => Promise<unknown>) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <SkillBindingsSection resource={resource} resourceId="resource" canEdit save={save} />
    </QueryClientProvider>
  );
}

describe("resource Skill bindings", () => {
  it("keeps saved order and activation mode until the assistant editor saves", async () => {
    get.mockImplementation(() =>
      ok({
        bindings: [summary("b", 2), summary("a", 1)],
        runtime: {
          fallback_reason: null,
          effective_mode: "selective",
          skill_context_tokens: 10,
          skill_context_token_limit: 100
        }
      })
    );
    const save = vi.fn().mockResolvedValue({});
    show("assistant", save);
    const list = await screen.findByRole("list", { name: "skills_binding_order_label" });
    expect(within(list).getAllByRole("listitem")[0]?.textContent).toContain("Skill a");
    expect(save).not.toHaveBeenCalled();
    fireEvent.change(screen.getAllByLabelText("skills_activation_mode_label")[0]!, {
      target: { value: "on_demand" }
    });
    fireEvent.click(screen.getAllByRole("button", { name: "skills_move_down_aria" })[0]!);
    expect(save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "skills_bindings_save" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith([
        { skill_id: "b", skill_revision_id: "revision-b", activation_mode: "always" },
        { skill_id: "a", skill_revision_id: "revision-a", activation_mode: "on_demand" }
      ])
    );
  });

  it("previews the exact published version before adding it to an app", async () => {
    get.mockImplementation((path: string) => {
      if (typeof path !== "string") return ok([]);
      if (path.endsWith("/apps/{app_id}/skills/")) return ok([]);
      if (path === "/api/v1/skills/catalogue/")
        return ok({
          items: [
            {
              id: "skill",
              revision_id: "revision",
              revision_number: 3,
              display_name: "Published Skill",
              description: "Use this skill",
              slug: "published",
              execution_blocked: false
            }
          ],
          next_cursor: null
        });
      if (path === "/api/v1/spaces/{space_id}/skills/") return ok({ items: [], next_cursor: null });
      if (path === "/api/v1/skills/catalogue/{skill_id}/")
        return ok({
          id: "skill",
          revision: {
            id: "revision",
            revision_number: 3,
            display_name: "Published Skill",
            description: "Use this skill",
            instructions: "Exact instructions"
          }
        });
      throw new Error(`Unexpected path: ${path}`);
    });
    const save = vi.fn().mockResolvedValue({});
    show("app", save);
    fireEvent.click(await screen.findByRole("button", { name: "skills_add_existing" }));
    fireEvent.click(await screen.findByRole("button", { name: /Published Skill/ }));
    expect(await screen.findByText("Exact instructions")).toBeTruthy();
    expect(save).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: "skills_add_to_draft" }));
    fireEvent.click(screen.getByRole("button", { name: "skills_bindings_save" }));
    await waitFor(() =>
      expect(save).toHaveBeenCalledWith([{ skill_id: "skill", skill_revision_id: "revision" }])
    );
  });

  it("keeps the draft after a rejected save", async () => {
    get.mockImplementation(() =>
      ok({
        bindings: [summary("a", 1)],
        runtime: {
          fallback_reason: null,
          effective_mode: "selective",
          skill_context_tokens: 10,
          skill_context_token_limit: 100
        }
      })
    );
    const save = vi.fn().mockRejectedValue(new Error("Denied"));
    show("assistant", save);
    fireEvent.change(await screen.findByLabelText("skills_activation_mode_label"), {
      target: { value: "on_demand" }
    });
    fireEvent.click(screen.getByRole("button", { name: "skills_bindings_save" }));
    await waitFor(() => expect(save).toHaveBeenCalledTimes(1));
    expect((screen.getByLabelText("skills_activation_mode_label") as HTMLSelectElement).value).toBe(
      "on_demand"
    );
    expect(
      screen.getByRole("button", { name: "skills_bindings_save" }).hasAttribute("disabled")
    ).toBe(false);
  });

  it("edits Personal Chat bindings inside the policy draft without saving separately", async () => {
    const onChange = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(
      <QueryClientProvider client={client}>
        <SkillBindingsEditor
          resource="personal_chat"
          spaceId="organization"
          organizationSpace
          canEdit
          canCreate={false}
          bindings={[{ skill_id: "a", skill_revision_id: "revision-a", activation_mode: "always" }]}
          summaries={[summary("a", 0)]}
          onChange={onChange}
          selectiveActivationEnabled
        />
      </QueryClientProvider>
    );
    fireEvent.change(screen.getByLabelText("skills_activation_mode_label"), {
      target: { value: "on_demand" }
    });
    expect(onChange).toHaveBeenCalledWith([
      { skill_id: "a", skill_revision_id: "revision-a", activation_mode: "on_demand" }
    ]);
    expect(screen.queryByRole("button", { name: "skills_bindings_save" })).toBeNull();
    expect(get).not.toHaveBeenCalled();
  });
});
