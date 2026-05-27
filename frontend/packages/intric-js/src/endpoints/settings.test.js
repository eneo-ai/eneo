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
