import type {
  FlowPackageDependencyResolution,
  FlowPackageExportResponse,
  FlowPackageImportPlan,
  FlowPackageImportResourceBinding,
  FlowPackageLocalCandidate,
  FlowPackageModelCandidate,
  FlowPackageOmission,
  FlowPackageResourceSlotRef
} from "@eneo/eneo-js";
import { EneoError } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";

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
  requiresTranscriptionModel: boolean;
  blockingReasons: FlowPackageImportBlockingReason[];
  selectedRequiredCount: number;
  totalRequiredCount: number;
  unresolvedRequiredCount: number;
  unsupportedTemplateAssetCount: number;
};

export type FlowPackageCandidate = FlowPackageLocalCandidate | FlowPackageModelCandidate;

export const FLOW_PACKAGE_IMPORT_ERROR_CODES = [
  "duplicate_slot_binding",
  "flow_package_base64_invalid",
  "flow_package_zip_unsafe",
  "flow_package_manifest_invalid",
  "flow_package_requirements_invalid",
  "flow_package_flow_draft_invalid",
  "flow_package_provenance_invalid",
  "flow_package_schema_unsupported",
  "flow_package_kind_unsupported",
  "flow_package_checksum_mismatch",
  "flow_package_local_resource_refs_not_portable",
  "flow_package_import_draft_references_undeclared_slot",
  "flow_package_import_unknown_resource_binding",
  "flow_package_import_missing_required_resource_binding",
  "flow_package_import_unavailable_local_resource",
  "flow_package_import_selected_model_ineligible",
  "flow_package_import_mcp_unsupported",
  "flow_package_import_template_assets_unsupported",
  "flow_package_file_too_large",
  "transcription_model_required"
] as const;

export const FLOW_PACKAGE_EXPORT_ERROR_CODES = [
  "flow_package_export_missing_assistant_snapshot",
  "flow_package_export_unsupported_step_io",
  "flow_package_export_step_config_not_portable",
  "flow_package_export_unmapped_resource_ref",
  "flow_package_export_duplicate_resource_binding",
  "flow_package_export_template_asset_payload_unsupported",
  "flow_package_export_variable_reference_invalid",
  "flow_package_export_json_payload_too_deep",
  "flow_package_export_form_schema_invalid",
  "flow_package_export_too_large"
] as const;

export type FlowPackageImportErrorCode = (typeof FLOW_PACKAGE_IMPORT_ERROR_CODES)[number];
export type FlowPackageExportErrorCode = (typeof FLOW_PACKAGE_EXPORT_ERROR_CODES)[number];
type FlowPackageErrorCode = FlowPackageImportErrorCode | FlowPackageExportErrorCode;
type FlowPackageErrorMessageKey = `flow_package_error_${FlowPackageErrorCode}`;

export function getFlowPackageSlotKey(
  slotRef: Pick<FlowPackageResourceSlotRef, "kind" | "slot">
): string {
  return `${slotRef.kind}.${slotRef.slot}`;
}

export function getFlowPackageResolutionSlotKey(
  resolution: FlowPackageDependencyResolution
): string {
  return getFlowPackageSlotKey(resolution.slot_ref);
}

export function getFlowPackageResolutionSlotLabel(
  resolution: FlowPackageDependencyResolution
): string {
  return resolution.slot_ref.label;
}

export function getFlowPackageCandidateKey(candidate: FlowPackageCandidate): string {
  return `${candidate.local_kind}:${candidate.local_id}`;
}

export function createInitialFlowPackageImportSelections(
  plan: FlowPackageImportPlan
): FlowPackageImportSelectionState {
  const selections: FlowPackageImportSelectionState = {};
  for (const resolution of plan.dependency_resolutions ?? []) {
    const slotRef = resolution.slot_ref;
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
    const slotRef = resolution.slot_ref;
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
  const requiresTranscriptionModel =
    plan.target_state.audio_transcription_required &&
    plan.target_state.default_transcription_model_id === null;

  for (const resolution of plan.dependency_resolutions ?? []) {
    const slotRef = resolution.slot_ref;
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

  // Backend owns the package plan; the browser owns readiness after the user changes selections.
  const canImport = !requiresTranscriptionModel && blockingReasons.length === 0;
  return {
    canImport,
    canPublishAfterImport: canImport && plan.can_publish_after_import,
    requiresTranscriptionModel,
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

export function getFlowPackageMcpOmissionCount(omissions: readonly FlowPackageOmission[]): number {
  return omissions.find((omission) => omission.kind === "mcp_attachment")?.count ?? 0;
}

export function downloadFlowPackageFile(
  response: FlowPackageExportResponse,
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

export function mapFlowPackageImportError(error: unknown): string | null {
  const code = getFlowPackageResponseCode(error);
  if (!code || !isFlowPackageImportErrorCode(code)) return null;
  return m[flowPackageErrorMessageKey(code)]();
}

export function mapFlowPackageExportError(error: unknown): string | null {
  const code = getFlowPackageResponseCode(error);
  if (!code || !isFlowPackageExportErrorCode(code)) return null;
  return m[flowPackageErrorMessageKey(code)]();
}

function indexFlowPackageCandidatesBySlot(
  plan: FlowPackageImportPlan
): Map<string, Map<string, FlowPackageCandidate>> {
  const candidatesBySlot = new Map<string, Map<string, FlowPackageCandidate>>();

  for (const resolution of plan.dependency_resolutions ?? []) {
    const slotRef = resolution.slot_ref;
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

function flowPackageErrorMessageKey(code: FlowPackageErrorCode): FlowPackageErrorMessageKey {
  return `flow_package_error_${code}`;
}

function isFlowPackageImportErrorCode(code: string): code is FlowPackageImportErrorCode {
  const codes: readonly string[] = FLOW_PACKAGE_IMPORT_ERROR_CODES;
  return codes.includes(code);
}

function isFlowPackageExportErrorCode(code: string): code is FlowPackageExportErrorCode {
  const codes: readonly string[] = FLOW_PACKAGE_EXPORT_ERROR_CODES;
  return codes.includes(code);
}

function getFlowPackageResponseCode(error: unknown): string | null {
  if (!(error instanceof EneoError)) return null;
  if (isObject(error.response) && typeof error.response.code === "string") {
    return error.response.code;
  }
  return typeof error.code === "string" ? error.code : null;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
