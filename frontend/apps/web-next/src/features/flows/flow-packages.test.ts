import { describe, expect, it } from "vitest";
import { EneoApiError } from "@/lib/api/errors";
import messages from "@/lib/i18n/messages/sv.json";
import {
  defaultPackageId,
  importReadiness,
  initialSelections,
  normalizePackageId,
  omittedCount,
  packageRefusalMessage,
  selectedBindings,
  type ImportPlan,
  type Resolution
} from "./flow-packages";

const catalog = messages as Record<string, string>;
const t = Object.assign(
  (key: string, values: Record<string, string | number> = {}) =>
    (catalog[key] ?? key).replace(/\{(\w+)\}/g, (_match, name: string) =>
      String(values[name] ?? `{${name}}`)
    ),
  { has: (key: string) => key in catalog }
);

const model = (overrides: Partial<Resolution> = {}): Resolution =>
  ({
    kind: "model",
    slot_ref: { kind: "model", slot: "writer", label: "Skrivmodell" },
    status: "requires_human_confirmation",
    required: true,
    selection_required_for_install: true,
    install_blocks: true,
    publish_blocks: true,
    auto_select_allowed: false,
    suggestions: [
      { local_kind: "completion_model", local_id: "m-1", label: "Modell A" },
      { local_kind: "completion_model", local_id: "m-2", label: "Modell B" }
    ],
    total_candidate_count: 2,
    eligible_candidate_count: 2,
    model_kind: "completion",
    matching_preferences: {},
    policy_status: "allowed",
    ...overrides
  }) as Resolution;

const plan = (resolutions: Resolution[], overrides: Partial<ImportPlan> = {}): ImportPlan =>
  ({
    can_install_as_draft: true,
    can_publish_after_import: true,
    content_checksum: "abc",
    dependency_resolutions: resolutions,
    kind: "flow",
    omissions: [],
    package_id: "local.brev",
    package_summary: {
      name: "Brev",
      description: "",
      requirements_by_kind: {},
      requirements_count: resolutions.length,
      spec_hash: "h",
      steps_count: 2
    },
    package_version: "1.0.0",
    payload_schema: "flow/v1",
    target_state: { audio_transcription_required: false, default_transcription_model_id: null },
    transcription_model_available: true,
    ...overrides
  }) as ImportPlan;

describe("package IDs", () => {
  it("makes an ID from the flow's name and keeps a typed one in the form an export takes", () => {
    expect(defaultPackageId("Rapport för nämnden")).toBe("local.rapport-for-namnden");
    expect(normalizePackageId("Se.Kommun..RapportFlöde")).toBe("se.kommun.rapportflode");
    expect(normalizePackageId("1a")).toBe("local.1a");
    expect(normalizePackageId("!!!")).toBe("");
  });

  it("cuts an overlong ID and keeps it distinct", () => {
    const long = normalizePackageId(`a${"b".repeat(200)}`);
    expect(long.length).toBeLessThanOrEqual(128);
    expect(long).not.toBe(normalizePackageId(`a${"b".repeat(201)}`));
  });

  it("reads the omission count the server states, and nothing else", () => {
    expect(omittedCount("3")).toBe(3);
    expect(omittedCount("0")).toBe(0);
    expect(omittedCount("x")).toBe(0);
    expect(omittedCount(null)).toBe(0);
  });
});

describe("import readiness", () => {
  it("blocks the import until a required resource is chosen, then sends that binding", () => {
    const current = plan([model()]);
    const selections = initialSelections(current);
    expect(selections).toEqual({ "model.writer": null });
    expect(importReadiness(current, selections)).toMatchObject({
      canImport: false,
      blockingReasons: [{ code: "required_mapping_missing", slotLabel: "Skrivmodell" }],
      selectedRequired: 0,
      totalRequired: 1
    });

    const chosen = { "model.writer": "completion_model:m-2" };
    expect(importReadiness(current, chosen)).toMatchObject({
      canImport: true,
      canPublishAfterImport: true,
      selectedRequired: 1
    });
    expect(selectedBindings(current, chosen)).toEqual([
      {
        slot_ref: { kind: "model", slot: "writer", label: "Skrivmodell" },
        local_kind: "completion_model",
        local_id: "m-2"
      }
    ]);
  });

  it("chooses the first suggestion where the plan may, and blocks what is unsupported", () => {
    const current = plan([
      model({ auto_select_allowed: true }),
      model({
        kind: "knowledge",
        slot_ref: { kind: "knowledge", slot: "docs", label: "Riktlinjer" },
        status: "unsupported"
      } as Partial<Resolution>)
    ]);
    const selections = initialSelections(current);
    expect(selections["model.writer"]).toBe("completion_model:m-1");
    expect(importReadiness(current, selections).blockingReasons).toEqual([
      expect.objectContaining({ code: "dependency_unsupported", kind: "knowledge" })
    ]);
  });

  it("refuses an audio package in a space without a transcription model", () => {
    const current = plan([], {
      target_state: { audio_transcription_required: true, default_transcription_model_id: null },
      transcription_model_available: false
    });
    expect(importReadiness(current, {})).toMatchObject({
      canImport: false,
      requiresTranscriptionModel: true
    });
  });
});

describe("package refusals", () => {
  const refusal = (reason: string, context: Record<string, unknown> = {}) =>
    new EneoApiError("Refused", { status: 400, reason, context });

  it("names the step and the settings an export refusal is about", () => {
    expect(
      packageRefusalMessage(
        refusal("flow_package_export_step_config_not_portable", {
          step_order: 2,
          config_field: "input_config"
        }),
        t
      )
    ).toBe(
      `${catalog.flow_editor_tools_package_error_flow_package_export_step_config_not_portable} Det gäller indatainställningarna i steg 2.`
    );
  });

  it("lists the fields a replacement template lacks", () => {
    expect(
      packageRefusalMessage(
        refusal("flow_package_template_fields_mismatch", { missing_fields: "namn, datum" }),
        t
      )
    ).toContain("Saknade taggar: namn, datum.");
  });

  it("falls back to the server's message for a code the catalog does not know", () => {
    expect(packageRefusalMessage(refusal("something_new"), t)).toBe("Refused");
  });
});
