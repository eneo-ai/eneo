import type {
  FlowClassificationRetentionPolicy,
  FlowClassificationRetentionPolicyPreviewRequest,
  SecurityClassification
} from "@eneo/eneo-js";
import { retentionDaysChangeIsDestructive } from "$lib/features/flows/flowRetentionPolicy";

export const FLOW_CLASSIFICATION_RETENTION_MIN_DAYS = 1;
export const FLOW_CLASSIFICATION_RETENTION_MAX_DAYS = 2555;

export type FlowClassificationRetentionDraft = {
  configuredDays: number | null;
  configuredMinimumDays: number | null;
  configuredNoPurge: boolean;
  draftDays: string;
  draftMinimumDays: string;
  draftNoPurge: boolean;
};

export type FlowClassificationRetentionDrafts = Record<string, FlowClassificationRetentionDraft>;

export type FlowClassificationRetentionRow = {
  id: string;
  name: string;
  description: string;
  securityLevel: number;
  hasPolicy: boolean;
  configuredDays: number | null;
  configuredMinimumDays: number | null;
  configuredNoPurge: boolean;
  draftDays: string;
  draftMinimumDays: string;
  draftNoPurge: boolean;
  hasChanges: boolean;
};

export type FlowClassificationRetentionParseResult =
  { ok: true; days: number | null } | { ok: false; reason: "integer" | "out_of_range" };

export function createFlowClassificationRetentionDrafts(
  policies: FlowClassificationRetentionPolicy[]
): FlowClassificationRetentionDrafts {
  return Object.fromEntries(
    policies.map((policy) => [
      policy.security_classification_id,
      {
        configuredDays: policy.data_retention_days,
        configuredMinimumDays: policy.minimum_retention_days,
        configuredNoPurge: policy.no_purge,
        draftDays: policy.data_retention_days?.toString() ?? "",
        draftMinimumDays: policy.minimum_retention_days?.toString() ?? "",
        draftNoPurge: policy.no_purge
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
    const configuredMinimumDays = draft?.configuredMinimumDays ?? null;
    const configuredNoPurge = draft?.configuredNoPurge ?? false;
    const draftDays = draft?.draftDays ?? "";
    const draftMinimumDays = draft?.draftMinimumDays ?? "";
    const draftNoPurge = draft?.draftNoPurge ?? false;

    return {
      id: classification.id,
      name: classification.name,
      description: classification.description ?? "",
      securityLevel: classification.security_level,
      hasPolicy: draft !== undefined,
      configuredDays,
      configuredMinimumDays,
      configuredNoPurge,
      draftDays,
      draftMinimumDays,
      draftNoPurge,
      hasChanges:
        draftDays.trim() !== (configuredDays?.toString() ?? "") ||
        draftMinimumDays.trim() !== (configuredMinimumDays?.toString() ?? "") ||
        draftNoPurge !== configuredNoPurge
    };
  });
}

function draftWithDefaults(
  current: FlowClassificationRetentionDraft | undefined
): FlowClassificationRetentionDraft {
  return (
    current ?? {
      configuredDays: null,
      configuredMinimumDays: null,
      configuredNoPurge: false,
      draftDays: "",
      draftMinimumDays: "",
      draftNoPurge: false
    }
  );
}

export function updateFlowClassificationRetentionDraft(
  drafts: FlowClassificationRetentionDrafts,
  securityClassificationId: string,
  draftDays: string
): FlowClassificationRetentionDrafts {
  return {
    ...drafts,
    [securityClassificationId]: {
      ...draftWithDefaults(drafts[securityClassificationId]),
      draftDays
    }
  };
}

export function updateFlowClassificationMinimumRetentionDraft(
  drafts: FlowClassificationRetentionDrafts,
  securityClassificationId: string,
  draftMinimumDays: string
): FlowClassificationRetentionDrafts {
  return {
    ...drafts,
    [securityClassificationId]: {
      ...draftWithDefaults(drafts[securityClassificationId]),
      draftMinimumDays
    }
  };
}

export function updateFlowClassificationNoPurgeDraft(
  drafts: FlowClassificationRetentionDrafts,
  securityClassificationId: string,
  draftNoPurge: boolean
): FlowClassificationRetentionDrafts {
  return {
    ...drafts,
    [securityClassificationId]: {
      ...draftWithDefaults(drafts[securityClassificationId]),
      draftNoPurge
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
      configuredMinimumDays: policy.minimum_retention_days,
      configuredNoPurge: policy.no_purge,
      draftDays: policy.data_retention_days?.toString() ?? "",
      draftMinimumDays: policy.minimum_retention_days?.toString() ?? "",
      draftNoPurge: policy.no_purge
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
  if (normalized === "") return { ok: true, days: null };

  const parsed = Number(normalized);
  if (!Number.isInteger(parsed)) return { ok: false, reason: "integer" };

  if (
    parsed < FLOW_CLASSIFICATION_RETENTION_MIN_DAYS ||
    parsed > FLOW_CLASSIFICATION_RETENTION_MAX_DAYS
  ) {
    return { ok: false, reason: "out_of_range" };
  }

  return { ok: true, days: parsed };
}

export function flowClassificationRetentionChangeIsDestructive(
  configuredDays: number | null,
  proposedDays: number | null
): boolean {
  return retentionDaysChangeIsDestructive(configuredDays, proposedDays);
}

export function flowClassificationRetentionChangeRequiresConfirmation(
  current: FlowClassificationRetentionPolicy | null,
  proposed: FlowClassificationRetentionPolicyPreviewRequest
): boolean {
  return (
    flowClassificationRetentionChangeIsDestructive(
      current?.data_retention_days ?? null,
      proposed.data_retention_days
    ) ||
    current?.minimum_retention_days !== proposed.minimum_retention_days ||
    (current?.no_purge ?? false) !== proposed.no_purge ||
    (current !== null &&
      proposed.data_retention_days === null &&
      proposed.minimum_retention_days === null &&
      !proposed.no_purge)
  );
}
