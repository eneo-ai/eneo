import { describe, expect, it } from "vitest";

import {
  buildFlowClassificationRetentionRows,
  clearFlowClassificationRetentionPolicyDraft,
  createFlowClassificationRetentionDrafts,
  flowClassificationRetentionChangeRequiresConfirmation,
  flowClassificationRetentionChangeIsDestructive,
  parseFlowClassificationRetentionDays,
  setFlowClassificationRetentionPolicyDraft,
  updateFlowClassificationRetentionDraft
} from "./flowClassificationRetentionPolicy";
import type { FlowClassificationRetentionPolicy, SecurityClassification } from "@eneo/eneo-js";

function classification(
  overrides: Partial<SecurityClassification> & Pick<SecurityClassification, "id" | "name">
): SecurityClassification {
  return {
    id: overrides.id,
    name: overrides.name,
    description: overrides.description ?? null,
    security_level: overrides.security_level ?? 0,
    created_at: overrides.created_at ?? null,
    updated_at: overrides.updated_at ?? null
  };
}

function policy(
  securityClassificationId: string,
  dataRetentionDays: number | null,
  minimumRetentionDays: number | null = null,
  noPurge = false
): FlowClassificationRetentionPolicy {
  return {
    security_classification_id: securityClassificationId,
    data_retention_days: dataRetentionDays,
    minimum_retention_days: minimumRetentionDays,
    no_purge: noPurge
  };
}

describe("flowClassificationRetentionPolicy", () => {
  it("maps classifications without policy rows to empty editable rows", () => {
    const rows = buildFlowClassificationRetentionRows(
      [
        classification({
          id: "class-1",
          name: "Class 1",
          description: null,
          security_level: 2
        })
      ],
      createFlowClassificationRetentionDrafts([])
    );

    expect(rows).toEqual([
      {
        id: "class-1",
        name: "Class 1",
        description: "",
        securityLevel: 2,
        hasPolicy: false,
        configuredDays: null,
        configuredMinimumDays: null,
        configuredNoPurge: false,
        draftDays: "",
        draftMinimumDays: "",
        draftNoPurge: false,
        hasChanges: false
      }
    ]);
  });

  it("maps configured policy rows without losing classification presentation", () => {
    const rows = buildFlowClassificationRetentionRows(
      [
        classification({
          id: "class-1",
          name: "Class 1",
          description: "Sensitive municipal data",
          security_level: 3
        })
      ],
      createFlowClassificationRetentionDrafts([policy("class-1", 7)])
    );

    expect(rows).toEqual([
      {
        id: "class-1",
        name: "Class 1",
        description: "Sensitive municipal data",
        securityLevel: 3,
        hasPolicy: true,
        configuredDays: 7,
        configuredMinimumDays: null,
        configuredNoPurge: false,
        draftDays: "7",
        draftMinimumDays: "",
        draftNoPurge: false,
        hasChanges: false
      }
    ]);
  });

  it("tracks local edits, saved responses, and cleared policies", () => {
    let drafts = createFlowClassificationRetentionDrafts([policy("class-1", 14)]);

    drafts = updateFlowClassificationRetentionDraft(drafts, "class-1", "7");
    expect(
      buildFlowClassificationRetentionRows(
        [classification({ id: "class-1", name: "Class 1" })],
        drafts
      )[0].hasChanges
    ).toBe(true);

    drafts = setFlowClassificationRetentionPolicyDraft(drafts, policy("class-1", 7));
    expect(
      buildFlowClassificationRetentionRows(
        [classification({ id: "class-1", name: "Class 1" })],
        drafts
      )[0]
    ).toMatchObject({
      hasPolicy: true,
      configuredDays: 7,
      draftDays: "7",
      hasChanges: false
    });

    drafts = clearFlowClassificationRetentionPolicyDraft(drafts, "class-1");
    expect(
      buildFlowClassificationRetentionRows(
        [classification({ id: "class-1", name: "Class 1" })],
        drafts
      )[0]
    ).toMatchObject({
      hasPolicy: false,
      configuredDays: null,
      draftDays: "",
      hasChanges: false
    });
  });

  it("accepts the backend retention range boundaries", () => {
    expect(parseFlowClassificationRetentionDays("1")).toEqual({ ok: true, days: 1 });
    expect(parseFlowClassificationRetentionDays("2555")).toEqual({
      ok: true,
      days: 2555
    });
  });

  it("accepts Off and rejects non-integer and out-of-range day values", () => {
    expect(parseFlowClassificationRetentionDays("")).toEqual({ ok: true, days: null });
    expect(parseFlowClassificationRetentionDays("7.5")).toEqual({
      ok: false,
      reason: "integer"
    });
    expect(parseFlowClassificationRetentionDays("0")).toEqual({
      ok: false,
      reason: "out_of_range"
    });
    expect(parseFlowClassificationRetentionDays("2556")).toEqual({
      ok: false,
      reason: "out_of_range"
    });
  });

  it("requires exact preview confirmation only for enable and shorten", () => {
    expect(flowClassificationRetentionChangeIsDestructive(null, 30)).toBe(true);
    expect(flowClassificationRetentionChangeIsDestructive(30, 14)).toBe(true);
    expect(flowClassificationRetentionChangeIsDestructive(30, 60)).toBe(false);
    expect(flowClassificationRetentionChangeIsDestructive(30, 30)).toBe(false);
    expect(
      flowClassificationRetentionChangeRequiresConfirmation(policy("class-1", null), {
        data_retention_days: null,
        minimum_retention_days: 90,
        no_purge: false
      })
    ).toBe(true);
    expect(
      flowClassificationRetentionChangeRequiresConfirmation(policy("class-1", 30, 90), {
        data_retention_days: null,
        minimum_retention_days: null,
        no_purge: false
      })
    ).toBe(true);
  });
});
