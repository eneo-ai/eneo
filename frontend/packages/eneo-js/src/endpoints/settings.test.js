import { describe, expect, it, vi } from "vitest";

import { initSettings } from "./settings";

describe("settings flow policy endpoints", () => {
  it("returns the resolved audio count while keeping the generic file count nullable", async () => {
    const limits = { audio_max_files_per_run: 10 };
    const fetch = vi.fn(async () => limits);
    const settings = initSettings({ fetch });

    await expect(settings.getFlowInputLimits()).resolves.toEqual({
      ...limits,
      max_files_per_run: null
    });
  });

  it("does not invent a nullable audio count when the get response breaches its contract", async () => {
    const fetch = vi.fn(async () => ({ max_files_per_run: null }));
    const settings = initSettings({ fetch });

    const limits = await settings.getFlowInputLimits();

    expect(limits).not.toHaveProperty("audio_max_files_per_run");
  });

  it("forwards an audio reset and returns the resolved audio count", async () => {
    const limits = {
      audio_max_files_per_run: 10,
      max_files_per_run: null
    };
    const fetch = vi.fn(async () => limits);
    const settings = initSettings({ fetch });

    await expect(
      settings.updateFlowInputLimits({ audio_max_files_per_run: null })
    ).resolves.toEqual(limits);
    expect(fetch).toHaveBeenCalledWith("/api/v1/settings/flow-input-limits", {
      method: "patch",
      requestBody: {
        "application/json": { audio_max_files_per_run: null }
      }
    });
  });

  it("does not invent a nullable audio count when the update response breaches its contract", async () => {
    const fetch = vi.fn(async () => ({ max_files_per_run: null }));
    const settings = initSettings({ fetch });

    const limits = await settings.updateFlowInputLimits({});

    expect(limits).not.toHaveProperty("audio_max_files_per_run");
  });

  it("gets flow retention policy from canonical settings route", async () => {
    const fetch = vi.fn(async () => ({ run_debug_evidence_days: 7 }));
    const settings = initSettings({ fetch });

    await settings.getFlowRetentionPolicy();

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/settings/flow-retention-policy");
    expect(fetch.mock.calls[0][1].method).toBe("get");
  });

  it("patches flow retention policy to canonical settings route", async () => {
    const fetch = vi.fn(async () => ({ run_debug_evidence_days: 14 }));
    const settings = initSettings({ fetch });

    await settings.updateFlowRetentionPolicy({
      run_debug_evidence_days: 14
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/settings/flow-retention-policy");
    expect(fetch.mock.calls[0][1]).toMatchObject({
      method: "patch",
      requestBody: {
        "application/json": {
          run_debug_evidence_days: 14
        }
      }
    });
  });

  it("gets flow evidence policy from canonical settings route", async () => {
    const fetch = vi.fn(async () => ({ allow_service_key_raw_export_class3: false }));
    const settings = initSettings({ fetch });

    await settings.getFlowEvidencePolicy();

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/settings/flow-evidence-policy");
    expect(fetch.mock.calls[0][1].method).toBe("get");
  });

  it("gets flow document render limits from canonical settings route", async () => {
    const fetch = vi.fn(async () => ({ max_source_chars: 500000 }));
    const settings = initSettings({ fetch });

    await settings.getFlowDocumentRenderLimits();

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/settings/flow-document-render-limits");
    expect(fetch.mock.calls[0][1].method).toBe("get");
  });

  it("patches flow document render limits to canonical settings route", async () => {
    const fetch = vi.fn(async () => ({ max_source_chars: 800000 }));
    const settings = initSettings({ fetch });

    await settings.updateFlowDocumentRenderLimits({ max_source_chars: 800000 });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/settings/flow-document-render-limits");
    expect(fetch.mock.calls[0][1]).toMatchObject({
      method: "patch",
      requestBody: {
        "application/json": {
          max_source_chars: 800000
        }
      }
    });
  });
});

describe("mapped execution settings endpoint", () => {
  it("loads the tenant mapped execution policy", async () => {
    const policy = {
      version: 1,
      max_provider_calls_per_mapped_step: 8,
      max_estimated_input_tokens_per_mapped_step: 90_000
    };
    const fetch = vi.fn(async () => policy);
    const settings = initSettings({ fetch });

    await expect(settings.getMappedExecutionPolicy()).resolves.toEqual(policy);
    expect(fetch).toHaveBeenCalledWith("/api/v1/settings/flow-mapped-execution-policy", {
      method: "get"
    });
  });

  it("preserves null clearing intent when updating the policy", async () => {
    const fetch = vi.fn(async () => ({
      version: 1,
      max_provider_calls_per_mapped_step: null,
      max_estimated_input_tokens_per_mapped_step: 90_000
    }));
    const settings = initSettings({ fetch });
    const policyPatch = { max_provider_calls_per_mapped_step: null };

    await settings.updateMappedExecutionPolicy(policyPatch);

    expect(fetch).toHaveBeenCalledWith("/api/v1/settings/flow-mapped-execution-policy", {
      method: "patch",
      requestBody: { "application/json": policyPatch }
    });
  });
});

describe("settings Skill policy endpoints", () => {
  it("uses the typed routes for organisation Skill execution blocks", async () => {
    const fetch = vi.fn(async () => ({ skill_id: "skill-1", block: null }));
    const settings = initSettings({ fetch });

    await settings.getSkillExecutionBlock({ skillId: "skill-1" });
    await settings.blockSkillExecution({
      skillId: "skill-1",
      reason: "Confirmed unsafe instructions"
    });
    await settings.unblockSkillExecution({
      skillId: "skill-1",
      expectedBlockId: "block-1",
      reason: "Removed the harmful revision"
    });

    expect(fetch.mock.calls).toEqual([
      [
        "/api/v1/settings/skills/{skill_id}/execution-block",
        { method: "get", params: { path: { skill_id: "skill-1" } } }
      ],
      [
        "/api/v1/settings/skills/{skill_id}/execution-block",
        {
          method: "post",
          params: { path: { skill_id: "skill-1" } },
          requestBody: {
            "application/json": { reason: "Confirmed unsafe instructions" }
          }
        }
      ],
      [
        "/api/v1/settings/skills/{skill_id}/execution-block/unblock",
        {
          method: "post",
          params: { path: { skill_id: "skill-1" } },
          requestBody: {
            "application/json": {
              expected_block_id: "block-1",
              reason: "Removed the harmful revision"
            }
          }
        }
      ]
    ]);
  });

  it("uses the typed admin routes for the Skill runtime policy", async () => {
    const policy = {
      selective_activation_enabled: true,
      max_attached_skills: 100,
      context_share_percent: 10,
      max_activations_per_turn: 3,
      editable_bounds: {
        max_attached_skills: { minimum: 1, maximum: 1000 },
        context_share_percent: { minimum: 1, maximum: 100 },
        max_activations_per_turn: { minimum: 1, maximum: 10 }
      }
    };
    const projections = { context_share_percent: 10, models: [] };
    const fetch = vi.fn(async (endpoint) =>
      endpoint.endsWith("model-projections") ? projections : policy
    );
    const settings = initSettings({ fetch });

    await expect(settings.getSkillRuntimePolicy()).resolves.toBe(policy);
    await expect(settings.updateSkillRuntimePolicy(policy)).resolves.toBe(policy);
    await expect(settings.resetSkillRuntimePolicy()).resolves.toBe(policy);
    await expect(settings.getSkillRuntimeModelProjections()).resolves.toBe(projections);

    expect(fetch.mock.calls).toEqual([
      ["/api/v1/settings/skills/runtime-policy", { method: "get" }],
      [
        "/api/v1/settings/skills/runtime-policy",
        {
          method: "put",
          requestBody: {
            "application/json": {
              selective_activation_enabled: true,
              max_attached_skills: 100,
              context_share_percent: 10,
              max_activations_per_turn: 3
            }
          }
        }
      ],
      ["/api/v1/settings/skills/runtime-policy/reset", { method: "post" }],
      ["/api/v1/settings/skills/runtime-policy/model-projections", { method: "get" }]
    ]);
  });
});
