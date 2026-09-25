import type { SkillRuntimeModelProjections, SkillRuntimePolicy } from "@eneo/eneo-js";
import { page } from "@vitest/browser/context";
import { render } from "vitest-browser-svelte";
import { describe, expect, test, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import SkillRuntimePolicySettings from "./SkillRuntimePolicySettings.svelte";

const policy: SkillRuntimePolicy = {
  selective_activation_enabled: true,
  max_attached_skills: 100,
  context_share_percent: 10,
  max_activations_per_turn: 3,
  editable_bounds: {
    max_attached_skills: { minimum: 1, maximum: 200 },
    context_share_percent: { minimum: 1, maximum: 50 },
    max_activations_per_turn: { minimum: 1, maximum: 6 }
  }
};

const modelProjections: SkillRuntimeModelProjections = {
  context_share_percent: 10,
  models: [
    {
      completion_model_id: "model-1",
      name: "openai/gpt-enterprise",
      nickname: "Enterprise",
      max_input_tokens: 128_000,
      supports_tool_calling: true,
      skill_context_token_allowance: 12_800
    }
  ]
};

describe("SkillRuntimePolicySettings", () => {
  test("saves one complete policy and refreshes the model projection", async () => {
    const savedPolicy = { ...policy, context_share_percent: 25 };
    const savedProjections = { ...modelProjections, context_share_percent: 25 };
    const onSave = vi.fn().mockResolvedValue({
      policy: savedPolicy,
      modelProjections: savedProjections
    });

    render(SkillRuntimePolicySettings, {
      initialPolicy: policy,
      initialModelProjections: modelProjections,
      onSave,
      onReset: vi.fn()
    });

    await page
      .getByRole("spinbutton", { name: m.skills_runtime_policy_context_share() })
      .fill("25");
    await page.getByRole("button", { name: m.skills_runtime_policy_save() }).click();

    await vi.waitFor(() =>
      expect(onSave).toHaveBeenCalledWith({
        selective_activation_enabled: true,
        max_attached_skills: 100,
        context_share_percent: 25,
        max_activations_per_turn: 3
      })
    );
    await expect
      .element(page.getByText(m.skills_runtime_policy_saved(), { exact: true }))
      .toBeVisible();
    await expect
      .element(
        page.getByText(m.skills_runtime_models_description({ percent: "25" }), { exact: true })
      )
      .toBeVisible();
  });

  test("reports a saved policy truthfully when the model projection cannot refresh", async () => {
    const savedPolicy = { ...policy, context_share_percent: 25 };
    const onSave = vi.fn().mockResolvedValue({
      policy: savedPolicy,
      modelProjections: null
    });

    render(SkillRuntimePolicySettings, {
      initialPolicy: policy,
      initialModelProjections: modelProjections,
      onSave,
      onReset: vi.fn()
    });

    await page
      .getByRole("spinbutton", { name: m.skills_runtime_policy_context_share() })
      .fill("25");
    await page.getByRole("button", { name: m.skills_runtime_policy_save() }).click();

    await expect
      .element(page.getByText(m.skills_runtime_policy_saved(), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByText(m.skills_runtime_models_unavailable_title(), { exact: true }))
      .toBeVisible();
  });

  test("uses backend bounds to block an invalid policy", async () => {
    const onSave = vi.fn();

    render(SkillRuntimePolicySettings, {
      initialPolicy: policy,
      initialModelProjections: modelProjections,
      onSave,
      onReset: vi.fn()
    });

    await page
      .getByRole("spinbutton", { name: m.skills_runtime_policy_max_attached() })
      .fill("201");

    await expect
      .element(page.getByText(m.skills_runtime_policy_invalid(), { exact: true }))
      .toBeVisible();
    await expect
      .element(page.getByRole("button", { name: m.skills_runtime_policy_save() }))
      .toBeDisabled();
    expect(onSave).not.toHaveBeenCalled();
  });

  test("confirms before restoring the backend defaults", async () => {
    const resetPolicy = { ...policy, max_attached_skills: 50 };
    const onReset = vi.fn().mockResolvedValue({
      policy: resetPolicy,
      modelProjections
    });

    render(SkillRuntimePolicySettings, {
      initialPolicy: policy,
      initialModelProjections: modelProjections,
      onSave: vi.fn(),
      onReset
    });

    await page.getByRole("button", { name: m.skills_runtime_policy_reset() }).click();
    await expect
      .element(page.getByText(m.skills_runtime_policy_reset_title(), { exact: true }))
      .toBeVisible();
    await page
      .getByRole("button", { name: m.skills_runtime_policy_reset(), exact: true })
      .last()
      .click();

    await vi.waitFor(() => expect(onReset).toHaveBeenCalledOnce());
    await expect
      .element(page.getByText(m.skills_runtime_policy_reset_done(), { exact: true }))
      .toBeVisible();
  });
});
