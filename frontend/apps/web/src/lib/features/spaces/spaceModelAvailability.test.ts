import { describe, expect, it } from "vitest";

import {
  hasAccessibleCompletionModel,
  hasAccessibleTranscriptionModel,
  linkedSpaceModelIds,
  spaceCanCreateApps,
  spaceSettingsModelRows
} from "./spaceModelAvailability";

describe("spaceModelAvailability", () => {
  it("uses model accessibility instead of model list presence", () => {
    expect(hasAccessibleCompletionModel([{ can_access: false }])).toBe(false);
    expect(hasAccessibleTranscriptionModel([{ can_access: false }])).toBe(false);
  });

  it("allows app creation only when completion and transcription models are accessible", () => {
    expect(
      spaceCanCreateApps({
        completion_models: [{ can_access: true }],
        transcription_models: [{ can_access: true }]
      })
    ).toBe(true);

    expect(
      spaceCanCreateApps({
        completion_models: [{ can_access: true }],
        transcription_models: [{ can_access: false }]
      })
    ).toBe(false);
  });

  it("resubmits every link the space reports, usable or not", () => {
    // A model list save replaces the space's links, so the IDs come from the
    // complete linked set, never from the usable lists alone.
    const link = (id: string, meets: boolean, available: boolean) => ({
      id,
      name: id,
      meets_security_classification: meets,
      available
    });
    const space = {
      completion_models: [{ id: "usable" }],
      embedding_models: [],
      transcription_models: [],
      linked_models: {
        completion_models: [
          link("usable", true, true),
          link("below", false, true),
          link("disabled", true, false),
          link("below-and-disabled", false, false)
        ],
        embedding_models: [link("embed", true, true)],
        transcription_models: []
      }
    };
    expect(linkedSpaceModelIds(space, "completion")).toEqual([
      "usable",
      "below",
      "disabled",
      "below-and-disabled"
    ]);
    expect(linkedSpaceModelIds(space, "embedding")).toEqual(["embed"]);
    expect(linkedSpaceModelIds(space, "transcription")).toEqual([]);
  });

  it("reports missing link state instead of an empty list", () => {
    // Without it a toggle would send only the new selection and unlink the
    // rest, so the editor must refuse to save rather than assume none.
    expect(linkedSpaceModelIds({}, "completion")).toBeNull();
    expect(
      linkedSpaceModelIds(
        {
          linked_models: { completion_models: [], embedding_models: [], transcription_models: [] }
        },
        "completion"
      )
    ).toEqual([]);
  });

  it("shows a row for every linked model, and for every addable one", () => {
    const link = (id: string, meets: boolean, available: boolean) => ({
      id,
      name: `name-${id}`,
      nickname: `Nick ${id}`,
      meets_security_classification: meets,
      available
    });
    const models = [
      { id: "enabled", is_org_enabled: true, is_deprecated: false },
      { id: "disabled-linked", is_org_enabled: false, is_deprecated: false },
      { id: "disabled-unlinked", is_org_enabled: false, is_deprecated: false },
      { id: "deprecated-linked", is_org_enabled: true, is_deprecated: true },
      { id: "migrated", is_org_enabled: true, is_deprecated: false, migrated_to_model_id: "x" }
    ];
    const rows = spaceSettingsModelRows(models, [
      link("disabled-linked", true, false),
      link("deprecated-linked", true, true),
      // Linked, but absent from the model catalogue: it still gets a row,
      // built from the link, so it can be switched off.
      link("not-in-catalogue", false, true)
    ]);
    expect(rows.map((m) => m.id)).toEqual([
      "enabled",
      "disabled-linked",
      "deprecated-linked",
      "not-in-catalogue"
    ]);
    expect(rows[3]).toMatchObject({
      name: "name-not-in-catalogue",
      nickname: "Nick not-in-catalogue",
      meets_security_classification: false,
      is_org_enabled: true
    });
  });
});
