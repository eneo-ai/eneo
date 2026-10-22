/**
 * Flow packages: a flow saved as a portable `.eneopkg` file, and a package
 * imported into a space as a new draft. The core plans an import (which
 * local models, knowledge and Word templates stand in for the package's) and
 * refuses what it cannot take; this module calls those endpoints, works out
 * what the person's choices still block, and turns every refusal into a
 * sentence. The reference editor (`flowPackageTransfer.ts` in apps/web) is
 * the behavioural spec.
 */
import { browserApi } from "@/lib/api/browser";
import { apiErrorFromResponse, EneoApiError, getErrorMessage, unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type ImportPlan = Schema<"FlowPackageImportPlan">;
export type ImportResult = Schema<"FlowPackageImportPublic">;
export type TemplateUpload = Schema<"FlowPackageTemplateUpload">;
export type Resolution = NonNullable<ImportPlan["dependency_resolutions"]>[number];
export type Candidate = Resolution["suggestions"][number];
export type ResourceBinding = Schema<"FlowPackageImportResourceBindingRequest">;

/** What `Eneo-Package-Omitted-Mcp-Assistant-Count` says an export left out. */
export const OMITTED_MCP_HEADER = "eneo-package-omitted-mcp-assistant-count";
const PACKAGE_EXTENSION = ".eneopkg";
/** The package ID length limit of `resource_packages/manifest.py`. */
export const PACKAGE_ID_MAX_LENGTH = 128;
/** Replacement Word templates together may be at most this large. */
export const TEMPLATE_UPLOAD_MAX_BYTES = 5 * 1024 * 1024;

// ---------------------------------------------------------------------------
// Export
// ---------------------------------------------------------------------------

export type PackageExport = {
  blob: Blob;
  filename: string | null;
  /** Step assistants whose MCP connections the package leaves out. */
  omittedMcpAssistants: number;
};

function filenameOf(contentDisposition: string | null): string | null {
  if (!contentDisposition) return null;
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(contentDisposition);
  if (utf8?.[1]) return decodeURIComponent(utf8[1].replaceAll("+", "%20"));
  return /filename="?([^";]+)"?/i.exec(contentDisposition)?.[1] ?? null;
}

/** A count the server states as a positive whole number; anything else counts as none. */
export function omittedCount(header: string | null): number {
  if (header === null || !/^[1-9]\d*$/.test(header)) return 0;
  const count = Number(header);
  return Number.isSafeInteger(count) ? count : 0;
}

export async function exportFlowPackage(
  flowId: string,
  body: Schema<"FlowPackageExportRequest">
): Promise<PackageExport> {
  const { data, error, response } = await browserApi.POST("/api/v1/flows/{id}/package-exports/", {
    params: { path: { id: flowId } },
    body,
    parseAs: "blob"
  });
  // A refusal comes back as JSON even though a success is a file.
  if (!response.ok || !data) throw apiErrorFromResponse(response, error);
  return {
    blob: data as Blob,
    filename: filenameOf(response.headers.get("content-disposition")),
    omittedMcpAssistants: omittedCount(response.headers.get(OMITTED_MCP_HEADER))
  };
}

/** A package ID made from the flow's name: `local.<slug>`. */
export function defaultPackageId(flowName: string): string {
  const slug = flowName
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return fitPackageId(`local.${slug || "flow-package"}`);
}

/** Cuts an overlong ID and keeps a hash of the whole, so cut IDs stay distinct. */
function fitPackageId(id: string): string {
  if (id.length <= PACKAGE_ID_MAX_LENGTH) return id;
  let hash = 0x811c9dc5;
  for (let index = 0; index < id.length; index += 1) {
    hash = Math.imul(hash ^ id.charCodeAt(index), 0x01000193) >>> 0;
  }
  const suffix = hash.toString(36);
  const head = id.slice(0, PACKAGE_ID_MAX_LENGTH - suffix.length - 1).replace(/[.-]+$/, "");
  return `${head}-${suffix}`;
}

/**
 * A typed ID in the lowercase dot or hyphen form an export accepts, so
 * "RapportFlöde" exports as "rapportflode" instead of being refused; "" when
 * nothing usable is left.
 */
export function normalizePackageId(value: string): string {
  const id = value
    .normalize("NFKD")
    .replace(/[̀-ͯ]/g, "")
    .toLowerCase()
    .replace(/[^a-z0-9.]+/g, "-")
    .replace(/-*\.[.-]*/g, ".")
    .replace(/^[.-]+|[.-]+$/g, "");
  if (!id) return "";
  return fitPackageId(/^[a-z]/.test(id) && id.length >= 3 ? id : `local.${id}`);
}

// ---------------------------------------------------------------------------
// Import
// ---------------------------------------------------------------------------

export function isPackageFile(file: Pick<File, "name">): boolean {
  return file.name.toLowerCase().endsWith(PACKAGE_EXTENSION);
}

/** A file's bytes as base64, read by the browser rather than byte by byte in script. */
export function fileToBase64(file: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => {
      const url = String(reader.result);
      resolve(url.slice(url.indexOf(",") + 1));
    };
    reader.onerror = () => reject(reader.error ?? new Error("The file could not be read."));
    reader.readAsDataURL(file);
  });
}

export function createImportPlan(
  spaceId: string,
  file: File,
  templateUploads: readonly TemplateUpload[],
  signal?: AbortSignal
): Promise<ImportPlan> {
  const body = new FormData();
  body.append("package_file", file);
  if (templateUploads.length > 0) {
    body.append(
      "template_uploads",
      new Blob([JSON.stringify(templateUploads)], { type: "application/json" }),
      "templates.json"
    );
  }
  return unwrap(
    browserApi.POST("/api/v1/spaces/{id}/flow-packages/import-plan/", {
      params: { path: { id: spaceId } },
      body: body as unknown as Schema<"Body_create_flow_package_import_plan">,
      bodySerializer: (formData: unknown) => formData as FormData,
      signal
    })
  );
}

export function importPackage(
  spaceId: string,
  body: Schema<"FlowPackageImportRequest">
): Promise<ImportResult> {
  return unwrap(
    browserApi.POST("/api/v1/spaces/{id}/flow-packages/imports/", {
      params: { path: { id: spaceId } },
      body
    })
  );
}

export function slotKey(resolution: Pick<Resolution, "slot_ref">): string {
  return `${resolution.slot_ref.kind}.${resolution.slot_ref.slot}`;
}

export function candidateKey(candidate: Pick<Candidate, "local_kind" | "local_id">): string {
  return `${candidate.local_kind}:${candidate.local_id}`;
}

/** The person's choice per package resource: a local candidate's key, or null for none. */
export type Selections = Record<string, string | null>;

/** The choices the plan recommends: its first suggestion where it may choose for the person. */
export function initialSelections(plan: ImportPlan): Selections {
  return Object.fromEntries(
    (plan.dependency_resolutions ?? []).map((resolution) => {
      const first = resolution.suggestions[0];
      return [
        slotKey(resolution),
        resolution.auto_select_allowed && first ? candidateKey(first) : null
      ];
    })
  );
}

/** The bindings the import sends for the choices made. */
export function selectedBindings(plan: ImportPlan, selections: Selections): ResourceBinding[] {
  return (plan.dependency_resolutions ?? []).flatMap((resolution) => {
    const chosen = selections[slotKey(resolution)];
    const candidate = resolution.suggestions.find((item) => candidateKey(item) === chosen);
    if (!chosen || !candidate) return [];
    return [
      {
        slot_ref: {
          kind: resolution.slot_ref.kind,
          slot: resolution.slot_ref.slot,
          label: resolution.slot_ref.label
        },
        local_kind: candidate.local_kind,
        local_id: candidate.local_id
      }
    ];
  });
}

export type BlockingReason = {
  code:
    | "required_mapping_missing"
    | "selected_resource_unavailable"
    | "dependency_unsupported"
    | "template_asset_unsupported"
    | "template_upload_missing";
  slotKey: string;
  slotLabel: string;
  kind: Resolution["kind"];
};

export type ImportReadiness = {
  canImport: boolean;
  canPublishAfterImport: boolean;
  /** The space has no transcription model the flow could use: nothing can be imported. */
  requiresTranscriptionModel: boolean;
  /** Imported without a model: its author chooses one before publishing. */
  transcriptionModelToChoose: boolean;
  blockingReasons: BlockingReason[];
  selectedRequired: number;
  totalRequired: number;
};

/** What the person's choices still block. The plan is the core's; readiness follows the choices. */
export function importReadiness(plan: ImportPlan, selections: Selections): ImportReadiness {
  const reasons: BlockingReason[] = [];
  let selectedRequired = 0;
  let totalRequired = 0;
  const takesAudio = plan.target_state.audio_transcription_required;
  const requiresTranscriptionModel = takesAudio && !plan.transcription_model_available;

  for (const resolution of plan.dependency_resolutions ?? []) {
    const key = slotKey(resolution);
    const reason = (code: BlockingReason["code"]) =>
      reasons.push({
        code,
        slotKey: key,
        slotLabel: resolution.slot_ref.label,
        kind: resolution.kind
      });
    const chosen = selections[key];
    const candidate = chosen
      ? resolution.suggestions.find((item) => candidateKey(item) === chosen)
      : undefined;

    if (resolution.kind === "template_asset" && resolution.template) {
      totalRequired += 1;
      if (resolution.install_blocks) reason("template_upload_missing");
      else selectedRequired += 1;
      continue;
    }
    if (resolution.status === "unsupported") {
      reason(
        resolution.kind === "template_asset"
          ? "template_asset_unsupported"
          : "dependency_unsupported"
      );
      continue;
    }
    if (chosen && !candidate) {
      reason("selected_resource_unavailable");
      continue;
    }
    if (resolution.selection_required_for_install) {
      totalRequired += 1;
      if (candidate) selectedRequired += 1;
      else reason("required_mapping_missing");
      continue;
    }
    if (resolution.install_blocks) {
      reason(
        resolution.kind === "template_asset"
          ? "template_asset_unsupported"
          : "dependency_unsupported"
      );
    }
  }

  const canImport = !requiresTranscriptionModel && reasons.length === 0;
  return {
    canImport,
    canPublishAfterImport: canImport && plan.can_publish_after_import,
    requiresTranscriptionModel,
    transcriptionModelToChoose:
      takesAudio &&
      plan.transcription_model_available &&
      plan.target_state.default_transcription_model_id === null,
    blockingReasons: reasons,
    selectedRequired,
    totalRequired
  };
}

/** The checksums the import states for the replacement templates the plan accepted. */
export function templateUploadChecksums(plan: ImportPlan): Record<string, string> {
  return Object.fromEntries(
    (plan.dependency_resolutions ?? []).flatMap((resolution) =>
      resolution.kind === "template_asset" && resolution.upload_checksum
        ? [[slotKey(resolution), resolution.upload_checksum]]
        : []
    )
  );
}

// ---------------------------------------------------------------------------
// Refusals
// ---------------------------------------------------------------------------

type Translator = ((key: string, values?: Record<string, string | number>) => string) & {
  has: (key: string) => boolean;
};

function contextOf(error: unknown): Record<string, unknown> {
  return error instanceof EneoApiError && error.context ? error.context : {};
}

/**
 * A refused export or import as a sentence: the package catalog's sentence
 * for its code, else the flow catalog's, else the server's message. An
 * export refusal names the step (and its input or output settings) it is
 * about; a template that does not match names the fields that differ.
 */
export function packageRefusalMessage(error: unknown, t: Translator): string {
  const code = error instanceof EneoApiError ? (error.reason ?? null) : null;
  const context = contextOf(error);
  let message: string;
  if (
    code === "flow_package_flow_draft_invalid" &&
    context.reason === "form_field_type_unsupported"
  ) {
    message = t("flow_editor_tools_package_error_form_field_type_unsupported");
  } else if (code && t.has(`flow_editor_tools_package_error_${code}`)) {
    message = t(`flow_editor_tools_package_error_${code}`);
  } else if (code && t.has(`flow_error_${code}`)) {
    message = t(`flow_error_${code}`);
  } else {
    message = getErrorMessage(error, t);
  }

  if (code === "flow_package_template_fields_mismatch") {
    const details = (
      [
        ["missing_fields", "flow_editor_tools_package_template_missing_fields"],
        ["added_fields", "flow_editor_tools_package_template_added_fields"],
        ["changed_fields", "flow_editor_tools_package_template_changed_fields"]
      ] as const
    ).flatMap(([field, key]) => {
      const value = context[field];
      return typeof value === "string" && value ? [t(key, { fields: value })] : [];
    });
    return [message, ...details].join(" ");
  }

  const step = context.step_order;
  if (code?.startsWith("flow_package_export") && typeof step === "number" && step >= 1) {
    const values = { message, step };
    if (context.config_field === "input_config") {
      return t("flow_editor_tools_package_export_error_in_step_input", values);
    }
    if (context.config_field === "output_config") {
      return t("flow_editor_tools_package_export_error_in_step_output", values);
    }
    return t("flow_editor_tools_package_export_error_in_step", values);
  }
  return message;
}
