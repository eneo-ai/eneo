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
  | "template_asset_unsupported"
  | "template_upload_missing";

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
  "flow_package_template_file_invalid",
  "flow_package_template_fields_mismatch",
  "flow_package_template_upload_required",
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
  "flow_package_import_name_collision",
  "flow_package_file_too_large",
  "transcription_model_required"
] as const;

export const FLOW_PACKAGE_EXPORT_ERROR_CODES = [
  "flow_package_export_template_bindings_incomplete",
  "flow_package_export_template_file_invalid",
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

// One message per code, named literally so a missing code is a type error and
// the catalogue's unused-key check sees every message in use.
const FLOW_PACKAGE_ERROR_MESSAGES = {
  flow_package_template_file_invalid: m.flow_package_error_flow_package_template_file_invalid,
  flow_package_template_fields_mismatch: m.flow_package_error_flow_package_template_fields_mismatch,
  flow_package_template_upload_required: m.flow_package_error_flow_package_template_upload_required,
  duplicate_slot_binding: m.flow_package_error_duplicate_slot_binding,
  flow_package_base64_invalid: m.flow_package_error_flow_package_base64_invalid,
  flow_package_zip_unsafe: m.flow_package_error_flow_package_zip_unsafe,
  flow_package_manifest_invalid: m.flow_package_error_flow_package_manifest_invalid,
  flow_package_requirements_invalid: m.flow_package_error_flow_package_requirements_invalid,
  flow_package_flow_draft_invalid: m.flow_package_error_flow_package_flow_draft_invalid,
  flow_package_provenance_invalid: m.flow_package_error_flow_package_provenance_invalid,
  flow_package_schema_unsupported: m.flow_package_error_flow_package_schema_unsupported,
  flow_package_kind_unsupported: m.flow_package_error_flow_package_kind_unsupported,
  flow_package_checksum_mismatch: m.flow_package_error_flow_package_checksum_mismatch,
  flow_package_local_resource_refs_not_portable:
    m.flow_package_error_flow_package_local_resource_refs_not_portable,
  flow_package_import_draft_references_undeclared_slot:
    m.flow_package_error_flow_package_import_draft_references_undeclared_slot,
  flow_package_import_unknown_resource_binding:
    m.flow_package_error_flow_package_import_unknown_resource_binding,
  flow_package_import_missing_required_resource_binding:
    m.flow_package_error_flow_package_import_missing_required_resource_binding,
  flow_package_import_unavailable_local_resource:
    m.flow_package_error_flow_package_import_unavailable_local_resource,
  flow_package_import_selected_model_ineligible:
    m.flow_package_error_flow_package_import_selected_model_ineligible,
  flow_package_import_mcp_unsupported: m.flow_package_error_flow_package_import_mcp_unsupported,
  flow_package_import_template_assets_unsupported:
    m.flow_package_error_flow_package_import_template_assets_unsupported,
  flow_package_import_name_collision: m.flow_package_error_flow_package_import_name_collision,
  flow_package_file_too_large: m.flow_package_error_flow_package_file_too_large,
  transcription_model_required: m.flow_package_error_transcription_model_required,
  flow_package_export_template_bindings_incomplete:
    m.flow_package_error_flow_package_export_template_bindings_incomplete,
  flow_package_export_template_file_invalid:
    m.flow_package_error_flow_package_export_template_file_invalid,
  flow_package_export_missing_assistant_snapshot:
    m.flow_package_error_flow_package_export_missing_assistant_snapshot,
  flow_package_export_unsupported_step_io:
    m.flow_package_error_flow_package_export_unsupported_step_io,
  flow_package_export_step_config_not_portable:
    m.flow_package_error_flow_package_export_step_config_not_portable,
  flow_package_export_unmapped_resource_ref:
    m.flow_package_error_flow_package_export_unmapped_resource_ref,
  flow_package_export_duplicate_resource_binding:
    m.flow_package_error_flow_package_export_duplicate_resource_binding,
  flow_package_export_template_asset_payload_unsupported:
    m.flow_package_error_flow_package_export_template_asset_payload_unsupported,
  flow_package_export_variable_reference_invalid:
    m.flow_package_error_flow_package_export_variable_reference_invalid,
  flow_package_export_json_payload_too_deep:
    m.flow_package_error_flow_package_export_json_payload_too_deep,
  flow_package_export_form_schema_invalid:
    m.flow_package_error_flow_package_export_form_schema_invalid,
  flow_package_export_too_large: m.flow_package_error_flow_package_export_too_large
} satisfies Record<FlowPackageErrorCode, () => string>;

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

    if (resolution.kind === "template_asset" && resolution.template) {
      totalRequiredCount += 1;
      if (resolution.install_blocks) {
        unresolvedRequiredCount += 1;
        blockingReasons.push({
          code: "template_upload_missing",
          slotKey,
          slotLabel: slotRef.label,
          kind: resolution.kind
        });
      } else {
        selectedRequiredCount += 1;
      }
      continue;
    }

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

export const FLOW_PACKAGE_EXTENSION = ".eneopkg";

/** A flow package is told apart by its extension: browsers report zip-based
 *  files under several media types, none of them specific to Eneo. */
export function isFlowPackageFile(file: Pick<File, "name">): boolean {
  return file.name.toLowerCase().endsWith(FLOW_PACKAGE_EXTENSION);
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
  return fitFlowPackageId(`local.${slug || "flow-package"}`);
}

// The package ID length limit of backend/src/eneo/resource_packages/manifest.py.
export const FLOW_PACKAGE_ID_MAX_LENGTH = 128;

/** Cuts an overlong ID and keeps a hash of the whole ID, so cut IDs stay distinct. */
function fitFlowPackageId(id: string): string {
  if (id.length <= FLOW_PACKAGE_ID_MAX_LENGTH) return id;
  const hash = fnv1a(id).toString(36);
  const head = id.slice(0, FLOW_PACKAGE_ID_MAX_LENGTH - hash.length - 1).replace(/[.-]+$/, "");
  return `${head}-${hash}`;
}

function fnv1a(text: string): number {
  let hash = 0x811c9dc5;
  for (let index = 0; index < text.length; index += 1) {
    hash = Math.imul(hash ^ text.charCodeAt(index), 0x01000193) >>> 0;
  }
  return hash;
}

/**
 * Rewrites a typed package ID into the lowercase dot or hyphen form export
 * accepts, so "RonnyVariant" exports as "ronnyvariant" instead of failing.
 * Returns "" when nothing usable is left.
 */
export function normalizeFlowPackageId(value: string): string {
  const id = value
    .normalize("NFKD")
    .replace(/[\u0300-\u036f]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9.]+/g, "-")
    .replace(/-*\.[.-]*/g, ".")
    .replace(/^[.-]+|[.-]+$/g, "");
  if (!id) return "";
  // A leading digit or a too-short ID becomes a segment of the local namespace.
  return fitFlowPackageId(/^[a-z]/.test(id) && id.length >= 3 ? id : `local.${id}`);
}

export function mapFlowPackageImportError(error: unknown): string | null {
  const code = getFlowPackageResponseCode(error);
  if (!code || !isFlowPackageImportErrorCode(code)) return null;
  const message = FLOW_PACKAGE_ERROR_MESSAGES[code]();
  if (code !== "flow_package_template_fields_mismatch") return message;
  const context = getFlowPackageResponseContext(error);
  const details = [
    typeof context?.missing_fields === "string" && context.missing_fields
      ? m.flow_package_template_missing_fields({ fields: context.missing_fields })
      : "",
    typeof context?.added_fields === "string" && context.added_fields
      ? m.flow_package_template_added_fields({ fields: context.added_fields })
      : "",
    typeof context?.changed_fields === "string" && context.changed_fields
      ? m.flow_package_template_changed_fields({ fields: context.changed_fields })
      : ""
  ].filter(Boolean);
  return [message, ...details].join(" ");
}

export function mapFlowPackageExportError(error: unknown): string | null {
  const code = getFlowPackageResponseCode(error);
  if (!code || !isFlowPackageExportErrorCode(code)) return null;
  const message = FLOW_PACKAGE_ERROR_MESSAGES[code]();
  // The server names the refused step and settings field, never their values.
  const context = getFlowPackageResponseContext(error);
  const step = context?.step_order;
  if (typeof step !== "number" || !Number.isInteger(step) || step < 1) return message;
  const args = { message, step: String(step) };
  if (context?.config_field === "input_config")
    return m.flow_package_export_error_in_step_input(args);
  if (context?.config_field === "output_config") {
    return m.flow_package_export_error_in_step_output(args);
  }
  return m.flow_package_export_error_in_step(args);
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

function getFlowPackageResponseContext(error: unknown): Record<string, unknown> | null {
  if (!(error instanceof EneoError) || !isObject(error.response)) return null;
  return isObject(error.response.context) ? error.response.context : null;
}

function isObject(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === "object" && !Array.isArray(value);
}
