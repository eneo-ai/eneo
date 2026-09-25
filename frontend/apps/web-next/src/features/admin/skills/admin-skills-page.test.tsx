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

  it("rejects values outside the backend bounds", async () => {
    show();
    await screen.findByRole("switch", { name: "skills_runtime_policy_selective_title" });
    fireEvent.change(screen.getByLabelText("skills_runtime_policy_max_attached"), {
      target: { value: "0" }
    });
    expect(
      screen.getByRole("button", { name: "skills_runtime_policy_save" }).hasAttribute("disabled")
    ).toBe(true);
    expect(put).not.toHaveBeenCalled();
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
});
