import type {
  FlowPackageDependencyResolution,
  FlowPackageImportPlan,
  FlowPackageImportResourceBinding,
  FlowPackageLocalCandidate,
  FlowPackageModelCandidate,
  FlowPackageResourceSlotRef,
  IntricBinaryResponse
} from "@intric/intric-js";

export type FlowPackageImportSelectionState = Record<string, string | null>;

export type FlowPackageImportBlockingReasonCode =
  | "required_mapping_missing"
  | "selected_resource_unavailable"
  | "dependency_unsupported"
  | "template_asset_unsupported";

export type FlowPackageImportBlockingReason = {
  code: FlowPackageImportBlockingReasonCode;
  slotKey: string;
  slotLabel: string;
  kind: FlowPackageDependencyResolution["kind"];
};

export type FlowPackageImportReadiness = {
  canImport: boolean;
  canPublishAfterImport: boolean;
  blockingReasons: FlowPackageImportBlockingReason[];
  selectedRequiredCount: number;
  totalRequiredCount: number;
  unresolvedRequiredCount: number;
  unsupportedTemplateAssetCount: number;
};

export type FlowPackageCandidate = FlowPackageLocalCandidate | FlowPackageModelCandidate;

const RESOURCE_SLOT_KINDS = new Set<FlowPackageResourceSlotRef["kind"]>([
  "model",
  "knowledge",
  "mcp_server",
  "mcp_tool",
  "template_asset"
]);

export function getFlowPackageSlotKey(
  slotRef: Pick<FlowPackageResourceSlotRef, "kind" | "slot">
): string {
  return `${slotRef.kind}.${slotRef.slot}`;
}

export function getFlowPackageResolutionSlotKey(
  resolution: FlowPackageDependencyResolution
): string {
  return getFlowPackageSlotKey(normalizeFlowPackageSlotRef(resolution.slot_ref));
}

export function getFlowPackageResolutionSlotLabel(
  resolution: FlowPackageDependencyResolution
): string {
  return normalizeFlowPackageSlotRef(resolution.slot_ref).label;
}

export function getFlowPackageCandidateKey(candidate: FlowPackageCandidate): string {
  return `${candidate.local_kind}:${candidate.local_id}`;
}

export function createInitialFlowPackageImportSelections(
  plan: FlowPackageImportPlan
): FlowPackageImportSelectionState {
  const selections: FlowPackageImportSelectionState = {};
  for (const resolution of plan.dependency_resolutions ?? []) {
    const slotRef = normalizeFlowPackageSlotRef(resolution.slot_ref);
    selections[getFlowPackageSlotKey(slotRef)] = getRecommendedCandidateKey(resolution);
  }
  return selections;
}

export function buildSelectedFlowPackageResourceBindings(
  plan: FlowPackageImportPlan,
  selections: FlowPackageImportSelectionState
): FlowPackageImportResourceBinding[] {
  const candidatesBySlot = indexFlowPackageCandidatesBySlot(plan);
  const bindings: FlowPackageImportResourceBinding[] = [];

  for (const resolution of plan.dependency_resolutions ?? []) {
    const slotRef = normalizeFlowPackageSlotRef(resolution.slot_ref);
    const slotKey = getFlowPackageSlotKey(slotRef);
    const selectedCandidateKey = selections[slotKey];
    if (!selectedCandidateKey) continue;

    const candidate = candidatesBySlot.get(slotKey)?.get(selectedCandidateKey);
    if (!candidate) {
      throw new Error(`Selected package resource is no longer available for ${slotKey}.`);
    }

    bindings.push({
      slot_ref: slotRef,
      local_kind: candidate.local_kind,
      local_id: candidate.local_id
    });
  }

  return bindings;
}

export function getFlowPackageImportReadiness(
  plan: FlowPackageImportPlan,
  selections: FlowPackageImportSelectionState
): FlowPackageImportReadiness {
  const candidatesBySlot = indexFlowPackageCandidatesBySlot(plan);
  const blockingReasons: FlowPackageImportBlockingReason[] = [];
  let selectedRequiredCount = 0;
  let totalRequiredCount = 0;
  let unresolvedRequiredCount = 0;
  let unsupportedTemplateAssetCount = 0;

  for (const resolution of plan.dependency_resolutions ?? []) {
    const slotRef = normalizeFlowPackageSlotRef(resolution.slot_ref);
    const slotKey = getFlowPackageSlotKey(slotRef);
    const selectedCandidateKey = selections[slotKey];
    const selectedCandidate = selectedCandidateKey
      ? candidatesBySlot.get(slotKey)?.get(selectedCandidateKey)
      : undefined;

    if (resolution.status === "unsupported") {
      if (resolution.kind === "template_asset") {
        unsupportedTemplateAssetCount += 1;
      }
      blockingReasons.push({
        code:
          resolution.kind === "template_asset"
            ? "template_asset_unsupported"
            : "dependency_unsupported",
        slotKey,
        slotLabel: slotRef.label,
        kind: resolution.kind
      });
      continue;
    }

    if (selectedCandidateKey && !selectedCandidate) {
      blockingReasons.push({
        code: "selected_resource_unavailable",
        slotKey,
        slotLabel: slotRef.label,
        kind: resolution.kind
      });
      continue;
    }

    if (resolution.selection_required_for_install) {
      totalRequiredCount += 1;
      if (selectedCandidate) {
        selectedRequiredCount += 1;
      } else {
        unresolvedRequiredCount += 1;
        blockingReasons.push({
          code: "required_mapping_missing",
          slotKey,
          slotLabel: slotRef.label,
          kind: resolution.kind
        });
      }
      continue;
    }

    if (resolution.install_blocks) {
      blockingReasons.push({
        code:
          resolution.kind === "template_asset"
            ? "template_asset_unsupported"
            : "dependency_unsupported",
        slotKey,
        slotLabel: slotRef.label,
        kind: resolution.kind
      });
    }
  }

  const canImport = blockingReasons.length === 0;
  return {
    canImport,
    canPublishAfterImport: canImport && plan.can_publish_after_import,
    blockingReasons,
    selectedRequiredCount,
    totalRequiredCount,
    unresolvedRequiredCount,
    unsupportedTemplateAssetCount
  };
}

export async function encodeFlowPackageFileToBase64(file: File): Promise<string> {
  const bytes = new Uint8Array(await file.arrayBuffer());
  const chunks: string[] = [];
  const chunkSize = 0x8000;

  // Large packages can exceed the argument limit of String.fromCharCode if
  // the whole Uint8Array is spread at once, so encode in bounded chunks.
  for (let offset = 0; offset < bytes.length; offset += chunkSize) {
    chunks.push(String.fromCharCode(...bytes.subarray(offset, offset + chunkSize)));
  }

  return btoa(chunks.join(""));
}

export function downloadFlowPackageFile(
  response: IntricBinaryResponse,
  fallbackFilename: string,
  deps: {
    document?: Pick<Document, "body" | "createElement">;
    url?: Pick<typeof URL, "createObjectURL" | "revokeObjectURL">;
  } = {}
): string {
  const documentRef = deps.document ?? document;
  const urlRef = deps.url ?? URL;
  const filename = response.filename?.trim() || fallbackFilename;
  const objectUrl = urlRef.createObjectURL(response.blob);
  const link = documentRef.createElement("a");

  link.href = objectUrl;
  link.download = filename;
  link.rel = "noopener";
  documentRef.body.appendChild(link);
  link.click();
  link.remove();
  urlRef.revokeObjectURL(objectUrl);

  return filename;
}

export function defaultFlowPackageId(flowName: string): string {
  const slug = flowName
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return `local.${slug || "flow-package"}`;
}

function indexFlowPackageCandidatesBySlot(
  plan: FlowPackageImportPlan
): Map<string, Map<string, FlowPackageCandidate>> {
  const candidatesBySlot = new Map<string, Map<string, FlowPackageCandidate>>();

  for (const resolution of plan.dependency_resolutions ?? []) {
    const slotRef = normalizeFlowPackageSlotRef(resolution.slot_ref);
    const slotKey = getFlowPackageSlotKey(slotRef);
    const candidates = new Map<string, FlowPackageCandidate>();
    for (const candidate of resolution.suggestions) {
      candidates.set(getFlowPackageCandidateKey(candidate), candidate);
    }
    candidatesBySlot.set(slotKey, candidates);
  }

  return candidatesBySlot;
}

function getRecommendedCandidateKey(resolution: FlowPackageDependencyResolution): string | null {
  if (!resolution.auto_select_allowed) return null;
  const [firstCandidate] = resolution.suggestions;
  return firstCandidate ? getFlowPackageCandidateKey(firstCandidate) : null;
}

function normalizeFlowPackageSlotRef(
  slotRef: FlowPackageDependencyResolution["slot_ref"]
): FlowPackageResourceSlotRef {
  const candidate = slotRef as Partial<FlowPackageResourceSlotRef>;
  if (
    typeof candidate.kind !== "string" ||
    !isResourceSlotKind(candidate.kind) ||
    typeof candidate.slot !== "string" ||
    typeof candidate.label !== "string"
  ) {
    throw new Error("Flow package import plan contains an invalid resource slot.");
  }

  return {
    kind: candidate.kind,
    slot: candidate.slot,
    label: candidate.label
  };
}

function isResourceSlotKind(value: string): value is FlowPackageResourceSlotRef["kind"] {
  return RESOURCE_SLOT_KINDS.has(value as FlowPackageResourceSlotRef["kind"]);
}
