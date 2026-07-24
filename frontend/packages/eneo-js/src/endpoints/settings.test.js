import { describe, expect, it, vi } from "vitest";

import { initSettings } from "./settings";

describe("settings flow policy endpoints", () => {
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

  it("previews exact flow retention impact on the canonical settings route", async () => {
    const preview = { preview_hash: "b".repeat(64) };
    const fetch = vi.fn(async () => preview);
    const settings = initSettings({ fetch });
    const proposal = {
      flow_run_history_retention_days: 30,
      flow_run_history_minimum_retention_days: null,
      flow_run_history_no_purge: false,
      flow_runtime_upload_abandonment_days: null
    };

    await expect(settings.previewFlowRetentionPolicy(proposal)).resolves.toBe(preview);

    expect(fetch).toHaveBeenCalledWith("/api/v1/settings/flow-retention-policy/preview", {
      method: "post",
      requestBody: { "application/json": proposal }
    });
  });

  it("lists flow classification retention policies from canonical settings route", async () => {
    const fetch = vi.fn(async () => ({
      policies: [
        {
          security_classification_id: "6f982fa9-8f74-451f-b6fc-773f937af7ef",
          data_retention_days: 7
        }
      ]
    }));
    const settings = initSettings({ fetch });

    await settings.listFlowClassificationRetentionPolicies();

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/settings/flow-classification-retention-policies");
    expect(fetch.mock.calls[0][1].method).toBe("get");
  });

  it("puts flow classification retention policy by classification id", async () => {
    const fetch = vi.fn(async () => ({
      security_classification_id: "6f982fa9-8f74-451f-b6fc-773f937af7ef",
      data_retention_days: 14
    }));
    const settings = initSettings({ fetch });

    await settings.putFlowClassificationRetentionPolicy("6f982fa9-8f74-451f-b6fc-773f937af7ef", {
      data_retention_days: 14,
      minimum_retention_days: null,
      no_purge: false
    });

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe(
      "/api/v1/settings/flow-classification-retention-policies/{security_classification_id}"
    );
    expect(fetch.mock.calls[0][1]).toMatchObject({
      method: "put",
      params: {
        path: {
          security_classification_id: "6f982fa9-8f74-451f-b6fc-773f937af7ef"
        }
      },
      requestBody: {
        "application/json": {
          data_retention_days: 14,
          minimum_retention_days: null,
          no_purge: false
        }
      }
    });
  });

  it("previews exact classification retention impact by classification id", async () => {
    const fetch = vi.fn(async () => ({ preview_hash: "b".repeat(64) }));
    const settings = initSettings({ fetch });
    const classificationId = "6f982fa9-8f74-451f-b6fc-773f937af7ef";

    await settings.previewFlowClassificationRetentionPolicy(classificationId, {
      data_retention_days: 14,
      minimum_retention_days: null,
      no_purge: false
    });

    expect(fetch).toHaveBeenCalledWith(
      "/api/v1/settings/flow-classification-retention-policies/{security_classification_id}/preview",
      {
        method: "post",
        params: { path: { security_classification_id: classificationId } },
        requestBody: {
          "application/json": {
            data_retention_days: 14,
            minimum_retention_days: null,
            no_purge: false
          }
        }
      }
    );
  });

  it("gets flow evidence policy from canonical settings route", async () => {
    const fetch = vi.fn(async () => ({ allow_service_key_raw_export_class3: false }));
    const settings = initSettings({ fetch });

    await settings.getFlowEvidencePolicy();

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/settings/flow-evidence-policy");
    expect(fetch.mock.calls[0][1].method).toBe("get");
  });

  it("gets AI Builder budget settings from canonical settings route", async () => {
    const fetch = vi.fn(async () => ({ minimum_conversation_budget_tokens: 4000 }));
    const settings = initSettings({ fetch });

    await settings.getAIBuilderBudgetSettings();

    expect(fetch).toHaveBeenCalledTimes(1);
    expect(fetch.mock.calls[0][0]).toBe("/api/v1/settings/ai-builder-budget");
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
