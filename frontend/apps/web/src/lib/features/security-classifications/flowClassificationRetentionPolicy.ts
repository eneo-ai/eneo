import type { FlowClassificationRetentionPolicy, SecurityClassification } from "@eneo/eneo-js";

export const FLOW_CLASSIFICATION_RETENTION_MIN_DAYS = 1;
export const FLOW_CLASSIFICATION_RETENTION_MAX_DAYS = 2555;

export type FlowClassificationRetentionDraft = {
  configuredDays: number | null;
  draftDays: string;
};

export type FlowClassificationRetentionDrafts = Record<string, FlowClassificationRetentionDraft>;

export type FlowClassificationRetentionRow = {
  id: string;
  name: string;
  description: string;
  securityLevel: number;
  hasPolicy: boolean;
  configuredDays: number | null;
  draftDays: string;
  hasChanges: boolean;
};

export type FlowClassificationRetentionParseResult =
  { ok: true; days: number } | { ok: false; reason: "empty" | "integer" | "out_of_range" };

export function createFlowClassificationRetentionDrafts(
  policies: FlowClassificationRetentionPolicy[]
): FlowClassificationRetentionDrafts {
  return Object.fromEntries(
    policies.map((policy) => [
      policy.security_classification_id,
      {
        configuredDays: policy.data_retention_days,
        draftDays: String(policy.data_retention_days)
      }
    ])
  );
}

export function buildFlowClassificationRetentionRows(
  classifications: SecurityClassification[],
  drafts: FlowClassificationRetentionDrafts
): FlowClassificationRetentionRow[] {
  return classifications.map((classification) => {
    const draft = drafts[classification.id];
    const configuredDays = draft?.configuredDays ?? null;
    const draftDays = draft?.draftDays ?? "";
    const configuredDraft = configuredDays === null ? "" : String(configuredDays);

    return {
      id: classification.id,
      name: classification.name,
      description: classification.description ?? "",
      securityLevel: classification.security_level,
      hasPolicy: configuredDays !== null,
      configuredDays,
      draftDays,
      hasChanges: draftDays.trim() !== configuredDraft
    };
  });
}

export function updateFlowClassificationRetentionDraft(
  drafts: FlowClassificationRetentionDrafts,
  securityClassificationId: string,
  draftDays: string
): FlowClassificationRetentionDrafts {
  const current = drafts[securityClassificationId];
  return {
    ...drafts,
    [securityClassificationId]: {
      configuredDays: current?.configuredDays ?? null,
      draftDays
    }
  };
}

export function setFlowClassificationRetentionPolicyDraft(
  drafts: FlowClassificationRetentionDrafts,
  policy: FlowClassificationRetentionPolicy
): FlowClassificationRetentionDrafts {
  return {
    ...drafts,
    [policy.security_classification_id]: {
      configuredDays: policy.data_retention_days,
      draftDays: String(policy.data_retention_days)
    }
  };
}

export function clearFlowClassificationRetentionPolicyDraft(
  drafts: FlowClassificationRetentionDrafts,
  securityClassificationId: string
): FlowClassificationRetentionDrafts {
  const next = { ...drafts };
  delete next[securityClassificationId];
  return next;
}

export function parseFlowClassificationRetentionDays(
  draftDays: string
): FlowClassificationRetentionParseResult {
  const normalized = draftDays.trim();
  if (normalized === "") {
    return { ok: false, reason: "empty" };
  }

  const parsed = Number(normalized);
  if (!Number.isInteger(parsed)) {
    return { ok: false, reason: "integer" };
  }

  if (
    parsed < FLOW_CLASSIFICATION_RETENTION_MIN_DAYS ||
    parsed > FLOW_CLASSIFICATION_RETENTION_MAX_DAYS
  ) {
    return { ok: false, reason: "out_of_range" };
  }

  return { ok: true, days: parsed };
}
