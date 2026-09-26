// @vitest-environment jsdom
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const get = vi.hoisted(() => vi.fn());
const put = vi.hoisted(() => vi.fn());
const post = vi.hoisted(() => vi.fn());
vi.mock("@/lib/api/browser", () => ({ browserApi: { GET: get, PUT: put, POST: post } }));
vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useLocale: () => "en"
}));

import { AdminSkillsPage } from "./admin-skills-page";

const policy = {
  selective_activation_enabled: false,
  max_attached_skills: 8,
  context_share_percent: 20,
  max_activations_per_turn: 3,
  editable_bounds: {
    max_attached_skills: { minimum: 1, maximum: 20 },
    context_share_percent: { minimum: 1, maximum: 50 },
    max_activations_per_turn: { minimum: 1, maximum: 10 }
  }
};
const ok = (data: unknown) =>
  Promise.resolve({ data, response: new Response("{}", { status: 200 }) });
beforeEach(() => {
  get.mockImplementation((path: string) =>
    path.endsWith("model-projections") ? ok({ context_share_percent: 20, models: [] }) : ok(policy)
  );
  put.mockImplementation(() => ok({ ...policy, selective_activation_enabled: true }));
  post.mockImplementation(() => ok(policy));
});
afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function show() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AdminSkillsPage />
    </QueryClientProvider>
  );
}

describe("admin skill runtime policy", () => {
  it("saves all four fields and refreshes the model projection", async () => {
    show();
    const toggle = await screen.findByRole("switch", {
      name: "skills_runtime_policy_selective_title"
    });
    fireEvent.click(toggle);
    fireEvent.change(screen.getByLabelText("skills_runtime_policy_context_share"), {
      target: { value: "30" }
    });
    fireEvent.click(screen.getByRole("button", { name: "skills_runtime_policy_save" }));
    await waitFor(() =>
      expect(put).toHaveBeenCalledWith("/api/v1/settings/skills/runtime-policy", {
        body: {
          selective_activation_enabled: true,
          max_attached_skills: 8,
          context_share_percent: 30,
          max_activations_per_turn: 3
        }
      })
    );
    expect(await screen.findByText("skills_runtime_policy_saved")).toBeTruthy();
    expect(
      get.mock.calls.filter(([path]) => String(path).endsWith("model-projections"))
    ).toHaveLength(2);
  });

  it("shows a value outside the backend bounds at its field on save, which takes focus", async () => {
    show();
    await screen.findByRole("switch", { name: "skills_runtime_policy_selective_title" });
    const field = screen.getByLabelText("skills_runtime_policy_context_share");
    fireEvent.change(field, { target: { value: "51" } });
    // Nothing is flagged while typing.
    expect(field.getAttribute("aria-invalid")).toBeNull();

    const save = screen.getByRole("button", { name: "skills_runtime_policy_save" });
    expect(save.hasAttribute("disabled")).toBe(false);
    fireEvent.click(save);

    expect(document.activeElement).toBe(field);
    expect(field.getAttribute("aria-invalid")).toBe("true");
    const describedBy = field.getAttribute("aria-describedby")?.split(" ") ?? [];
    expect(describedBy.map((id) => document.getElementById(id)?.textContent)).toEqual([
      "skills_runtime_policy_invalid",
      "skills_runtime_policy_context_share_description",
      "skills_runtime_policy_allowed_range"
    ]);
    // The other limits are within bounds.
    expect(
      screen.getByLabelText("skills_runtime_policy_max_attached").getAttribute("aria-invalid")
    ).toBeNull();
    expect(put).not.toHaveBeenCalled();

    fireEvent.change(field, { target: { value: "50" } });
    expect(field.getAttribute("aria-invalid")).toBeNull();
    fireEvent.click(save);
    await waitFor(() => expect(put).toHaveBeenCalledTimes(1));
  });

  it("keeps focus on Save while it saves, and says when there is nothing to save", async () => {
    let resolve: (value: unknown) => void = () => {};
    put.mockImplementation(
      () =>
        new Promise((done) => {
          resolve = done;
        })
    );
    show();
    const save = await screen.findByRole("button", { name: "skills_runtime_policy_save" });

    fireEvent.click(save);
    expect(await screen.findByText("form_nothing_to_save")).toBeTruthy();
    expect(put).not.toHaveBeenCalled();

    fireEvent.change(screen.getByLabelText("skills_runtime_policy_max_attached"), {
      target: { value: "9" }
    });
    save.focus();
    fireEvent.click(save);
    const busy = await screen.findByRole("button", { name: "skills_runtime_policy_saving" });
    expect(busy).toBe(save);
    expect(busy.getAttribute("aria-busy")).toBe("true");
    expect(busy.hasAttribute("disabled")).toBe(false);
    expect(document.activeElement).toBe(busy);
    fireEvent.click(busy);
    expect(put).toHaveBeenCalledTimes(1);

    resolve({ data: { ...policy, max_attached_skills: 9 }, response: new Response("{}") });
    expect(await screen.findByText("skills_runtime_policy_saved")).toBeTruthy();
    expect(document.activeElement).toBe(save);
  });

  it("requires confirmation to reset the policy", async () => {
    show();
    fireEvent.click(await screen.findByRole("button", { name: "skills_runtime_policy_reset" }));
    expect(post).not.toHaveBeenCalled();
    fireEvent.click(
      within(screen.getByRole("alertdialog")).getByRole("button", {
        name: "skills_runtime_policy_reset"
      })
    );
    await waitFor(() =>
      expect(post).toHaveBeenCalledWith("/api/v1/settings/skills/runtime-policy/reset")
    );
    expect(await screen.findByText("skills_runtime_policy_reset_done")).toBeTruthy();
  });

  it("names the model impact table by its heading", async () => {
    get.mockImplementation((path: string) =>
      path.endsWith("model-projections")
        ? ok({
            context_share_percent: 20,
            models: [
              {
                completion_model_id: "model-1",
                name: "gpt-5",
                nickname: null,
                max_input_tokens: 400_000,
                skill_context_token_allowance: 80_000,
                supports_tool_calling: true
              }
            ]
          })
        : ok(policy)
    );
    show();

    const table = await screen.findByRole("table", { name: "skills_runtime_models_title" });
    expect(within(table).getByText("gpt-5")).toBeTruthy();
  });
});
