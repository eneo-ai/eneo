// @vitest-environment jsdom
import { describe, expect, it, vi } from "vitest";
import { EneoError, type FlowPackageImportPlan } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

import {
  FLOW_PACKAGE_EXPORT_ERROR_CODES,
  FLOW_PACKAGE_IMPORT_ERROR_CODES,
  type FlowPackageExportErrorCode,
  type FlowPackageImportErrorCode,
  buildSelectedFlowPackageResourceBindings,
  createInitialFlowPackageImportSelections,
  defaultFlowPackageId,
  downloadFlowPackageFile,
  encodeFlowPackageFileToBase64,
  getFlowPackageImportReadiness,
  mapFlowPackageExportError,
  mapFlowPackageImportError
} from "./flowPackageTransfer";

describe("flowPackageTransfer", () => {
  it("preselects the recommended candidate and builds typed resource bindings", () => {
    const plan = flowPackageImportPlan();

    const selections = createInitialFlowPackageImportSelections(plan);
    const readiness = getFlowPackageImportReadiness(plan, selections);
    const bindings = buildSelectedFlowPackageResourceBindings(plan, selections);

    expect(selections).toEqual({
      "model.structured-extraction": `completion_model:${MODEL_ID}`,
      "knowledge.local-rules": null
    });
    expect(readiness).toMatchObject({
      canImport: true,
      canPublishAfterImport: true,
      requiresTranscriptionModel: false,
      selectedRequiredCount: 1,
      totalRequiredCount: 1,
      unresolvedRequiredCount: 0
    });
    expect(bindings).toEqual([
      {
        slot_ref: {
          kind: "model",
          slot: "structured-extraction",
          label: "Structured extraction"
        },
        local_kind: "completion_model",
        local_id: MODEL_ID
      }
    ]);
  });

  it("blocks import when an install-blocking model has no selected local resource", () => {
    const plan = flowPackageImportPlan({
      can_install_as_draft: false,
      can_publish_after_import: false,
      dependency_resolutions: [
        {
          kind: "model",
          slot_ref: {
            kind: "model",
            slot: "structured-extraction",
            label: "Structured extraction"
          },
          required: true,
          used_by_steps: ["extract-fields"],
          data_sensitivity: null,
          status: "unresolved_required",
          install_blocks: true,
          publish_blocks: true,
          selection_required_for_install: true,
          auto_select_allowed: false,
          suggestions: [],
          total_candidate_count: 0,
          guidance: null,
          model_kind: "completion_model",
          matching_preferences: {
            tested_with: [],
            publisher_suggested: []
          },
          completion_constraints: null,
          eligible_candidate_count: 0,
          policy_status: "allowed",
          selection_warnings: [],
          rejected_candidates: []
        }
      ]
    });

    const readiness = getFlowPackageImportReadiness(plan, {});

    expect(readiness.canImport).toBe(false);
    expect(readiness.blockingReasons).toEqual([
      {
        code: "required_mapping_missing",
        slotKey: "model.structured-extraction",
        slotLabel: "Structured extraction",
        kind: "model"
      }
    ]);
  });

  it("blocks import when required knowledge has no local mapping", () => {
    const plan = flowPackageImportPlan({
      can_install_as_draft: false,
      can_publish_after_import: false,
      dependency_resolutions: [
        {
          kind: "knowledge",
          slot_ref: { kind: "knowledge", slot: "local-rules", label: "Local rules" },
          required: true,
          used_by_steps: ["compose-report"],
          data_sensitivity: null,
          status: "unresolved_required",
          install_blocks: true,
          publish_blocks: true,
          selection_required_for_install: true,
          auto_select_allowed: false,
          suggestions: [],
          total_candidate_count: 0,
          guidance: null
        }
      ]
    });

    const readiness = getFlowPackageImportReadiness(plan, {});

    expect(readiness).toMatchObject({
      canImport: false,
      canPublishAfterImport: false,
      selectedRequiredCount: 0,
      totalRequiredCount: 1,
      unresolvedRequiredCount: 1,
      blockingReasons: [
        {
          code: "required_mapping_missing",
          slotKey: "knowledge.local-rules",
          slotLabel: "Local rules",
          kind: "knowledge"
        }
      ]
    });
  });

  it("blocks import when an audio package has no target transcription model", () => {
    const plan = flowPackageImportPlan({
      can_install_as_draft: false,
      can_publish_after_import: false,
      target_state: {
        audio_transcription_required: true,
        default_transcription_model_id: null
      }
    });

    const readiness = getFlowPackageImportReadiness(
      plan,
      createInitialFlowPackageImportSelections(plan)
    );

    expect(readiness).toMatchObject({
      canImport: false,
      canPublishAfterImport: false,
      requiresTranscriptionModel: true
    });
  });

  it("does not preselect candidates that require human confirmation", () => {
    const modelResolution = flowPackageImportPlan().dependency_resolutions?.[0];
    if (!modelResolution) throw new Error("Expected sample model resolution.");
    const plan = flowPackageImportPlan({
      can_publish_after_import: false,
      can_install_as_draft: true,
      dependency_resolutions: [
        {
          ...modelResolution,
          status: "requires_human_confirmation",
          install_blocks: false,
          publish_blocks: true,
          selection_required_for_install: true,
          auto_select_allowed: false
        }
      ]
    });

    const selections = createInitialFlowPackageImportSelections(plan);
    const readiness = getFlowPackageImportReadiness(plan, selections);

    expect(selections).toEqual({
      "model.structured-extraction": null
    });
    expect(readiness.canImport).toBe(false);
    expect(readiness.blockingReasons[0]).toMatchObject({
      code: "required_mapping_missing",
      slotKey: "model.structured-extraction"
    });
  });

  it("blocks template asset packages until template installation has a canonical backend owner", () => {
    const plan = flowPackageImportPlan({
      dependency_resolutions: [
        {
          kind: "template_asset",
          slot_ref: { kind: "template_asset", slot: "report-template", label: "Report template" },
          required: false,
          used_by_steps: ["render-report"],
          data_sensitivity: null,
          status: "unsupported",
          install_blocks: true,
          publish_blocks: true,
          selection_required_for_install: false,
          auto_select_allowed: false,
          suggestions: [],
          total_candidate_count: 0,
          guidance: null
        }
      ]
    });

    const readiness = getFlowPackageImportReadiness(plan, {});

    expect(readiness.canImport).toBe(false);
    expect(readiness.unsupportedTemplateAssetCount).toBe(1);
    expect(readiness.blockingReasons[0]).toMatchObject({
      code: "template_asset_unsupported",
      slotKey: "template_asset.report-template"
    });
  });

  it("maps public import error codes to package-specific copy", () => {
    for (const code of FLOW_PACKAGE_IMPORT_ERROR_CODES) {
      const error = new EneoError(code, "RESPONSE", 400, 0, { code }, { endpoint: "POST@test" });

      expect(mapFlowPackageImportError(error)).toBe(expectedFlowPackageErrorMessage(code));
    }
  });

  it("maps public export error codes to package-specific copy", () => {
    for (const code of FLOW_PACKAGE_EXPORT_ERROR_CODES) {
      const error = new EneoError(code, "RESPONSE", 400, 0, { code }, { endpoint: "POST@test" });

      expect(mapFlowPackageExportError(error)).toBe(expectedFlowPackageErrorMessage(code));
    }
  });

  it("maps package error codes from legacy client code fields when response codes are absent", () => {
    const importError = new EneoError(
      "missing binding",
      "RESPONSE",
      400,
      0,
      {},
      { endpoint: "POST@test" }
    );
    Object.defineProperty(importError, "code", {
      value: "flow_package_import_missing_required_resource_binding"
    });

    expect(mapFlowPackageImportError(importError)).toBe(
      expectedFlowPackageErrorMessage("flow_package_import_missing_required_resource_binding")
    );

    const exportError = new EneoError("step config not portable", "RESPONSE", 400, 0, undefined, {
      endpoint: "POST@test"
    });
    Object.defineProperty(exportError, "code", {
      value: "flow_package_export_step_config_not_portable"
    });

    expect(mapFlowPackageExportError(exportError)).toBe(
      expectedFlowPackageErrorMessage("flow_package_export_step_config_not_portable")
    );
  });

  it("ignores unknown package error codes so dialogs can fall back to server text", () => {
    const error = new EneoError(
      "unknown",
      "RESPONSE",
      400,
      0,
      { code: "not_a_flow_package_error" },
      { endpoint: "POST@test" }
    );

    expect(mapFlowPackageImportError(error)).toBeNull();
    expect(mapFlowPackageExportError(error)).toBeNull();
  });

  it("encodes package files to base64 without relying on whole-array string spreading", async () => {
    const file = new File(["hello"], "hello.eneopkg");

    await expect(encodeFlowPackageFileToBase64(file)).resolves.toBe("aGVsbG8=");
  });

  it("downloads binary package responses with the server filename when available", () => {
    const { link, body, documentRef, urlRef } = flowPackageDownloadDeps();

    const filename = downloadFlowPackageFile(
      {
        blob: new Blob(["pkg"]),
        contentType: "application/octet-stream",
        filename: "se.demo.case-report-1.0.0.eneopkg",
        headers: new Headers()
      },
      "fallback.eneopkg",
      { document: documentRef, url: urlRef }
    );

    expect(filename).toBe("se.demo.case-report-1.0.0.eneopkg");
    expect(link.download).toBe("se.demo.case-report-1.0.0.eneopkg");
    expect(link.href).toBe("blob:package");
    expect(body.appendChild).toHaveBeenCalledWith(link);
    expect(link.click).toHaveBeenCalledOnce();
    expect(link.remove).toHaveBeenCalledOnce();
    expect(urlRef.revokeObjectURL).toHaveBeenCalledWith("blob:package");
  });

  it("uses the generic fallback filename only when the server omits a filename", () => {
    const { link, documentRef, urlRef } = flowPackageDownloadDeps();

    const filename = downloadFlowPackageFile(
      {
        blob: new Blob(["pkg"]),
        contentType: "application/octet-stream",
        headers: new Headers()
      },
      "flow-package.eneopkg",
      { document: documentRef, url: urlRef }
    );

    expect(filename).toBe("flow-package.eneopkg");
    expect(link.download).toBe("flow-package.eneopkg");
  });

  it("creates safe default package identifiers", () => {
    expect(defaultFlowPackageId("Mötesrapport från ljud")).toBe("local.motesrapport-fran-ljud");
    expect(defaultFlowPackageId("")).toBe("local.flow-package");
  });
});

function flowPackageDownloadDeps() {
  const link = {
    href: "",
    download: "",
    rel: "",
    click: vi.fn(),
    remove: vi.fn()
  } as unknown as HTMLAnchorElement;
  const body = { appendChild: vi.fn() } as unknown as HTMLBodyElement;
  const documentRef = {
    body,
    createElement: vi.fn(() => link)
  } as unknown as Pick<Document, "body" | "createElement">;
  const urlRef = {
    createObjectURL: vi.fn(() => "blob:package"),
    revokeObjectURL: vi.fn()
  };

  return { link, body, documentRef, urlRef };
}

const MODEL_ID = "11111111-1111-4111-8111-111111111111";
const KNOWLEDGE_ID = "22222222-2222-4222-8222-222222222222";

type FlowPackageErrorCode = FlowPackageImportErrorCode | FlowPackageExportErrorCode;
type FlowPackageErrorMessageKey = `flow_package_error_${FlowPackageErrorCode}`;

function expectedFlowPackageErrorMessage(code: FlowPackageErrorCode): string {
  return m[`flow_package_error_${code}` as FlowPackageErrorMessageKey]();
}

function flowPackageImportPlan(
  overrides: Partial<FlowPackageImportPlan> = {}
): FlowPackageImportPlan {
  return {
    package_id: "se.demo.report",
    package_version: "1.0.0",
    kind: "flow",
    payload_schema: "eneo.flow_package.v1",
    content_checksum: "abc123",
    package_summary: {
      name: "Demo report",
      description: "Creates a report from imported material.",
      spec_hash: "spec123",
      steps_count: 2,
      requirements_count: 2,
      requirements_by_kind: {
        model: 1,
        knowledge: 1
      }
    },
    target_state: {
      audio_transcription_required: false,
      default_transcription_model_id: null
    },
    can_publish_after_import: true,
    can_install_as_draft: true,
    dependency_resolutions: [
      {
        kind: "model",
        slot_ref: { kind: "model", slot: "structured-extraction", label: "Structured extraction" },
        required: true,
        used_by_steps: ["extract-fields"],
        data_sensitivity: {
          handles_personal_data: true,
          handles_sensitive_case_data: false,
          publisher_classification_label: "K2",
          publisher_classification_description: null,
          notes: null
        },
        status: "resolved_exact",
        install_blocks: false,
        publish_blocks: false,
        selection_required_for_install: true,
        auto_select_allowed: true,
        suggestions: [
          {
            local_kind: "completion_model",
            local_id: MODEL_ID,
            label: "GPT test",
            model_kind: "completion_model",
            identity: { provider: "openai", model: "gpt-test" },
            security_level: 3,
            max_context_tokens: 32000,
            supports_vision: false,
            supports_reasoning: true,
            supports_tool_calling: false
          }
        ],
        total_candidate_count: 1,
        guidance: null,
        model_kind: "completion_model",
        matching_preferences: {
          tested_with: [{ provider: "openai", model: "gpt-test" }],
          publisher_suggested: []
        },
        completion_constraints: null,
        eligible_candidate_count: 1,
        policy_status: "allowed",
        selection_warnings: [],
        rejected_candidates: []
      },
      {
        kind: "knowledge",
        slot_ref: { kind: "knowledge", slot: "local-rules", label: "Local rules" },
        required: false,
        used_by_steps: ["compose-report"],
        data_sensitivity: null,
        status: "skipped_optional",
        install_blocks: false,
        publish_blocks: false,
        selection_required_for_install: false,
        auto_select_allowed: false,
        suggestions: [
          {
            local_kind: "collection",
            local_id: KNOWLEDGE_ID,
            label: "Shared rules"
          }
        ],
        total_candidate_count: 1,
        guidance: null
      }
    ],
    ...overrides
  };
}
