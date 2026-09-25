import type { Capability } from "@/features/capabilities/capabilities";
import type {
  McpServer,
  McpServerCreatePayload,
  McpServerUpdatePayload
} from "@/features/admin/mcp/mcp";

export type SourceDraft = {
  name: string;
  description: string;
  source: "external" | "builtin";
  url: string;
  auth: "none" | "bearer" | "api_key_header";
  token: string;
  headerName: string;
  imageModelId: string;
  audience: "everyone" | "groups";
  priority: number;
  groupIds: string[];
  forwardIdentity: boolean;
  documentationUrl: string;
  classificationId: string;
  toolCatalogMaxCount: number;
  toolCatalogMaxMiB: number;
  toolDefinitionMaxKiB: number;
};

export function sourceDraft(server?: McpServer | null): SourceDraft {
  return {
    name: server?.name ?? "",
    description: server?.description ?? "",
    source: server?.http_auth_type === "internal" ? "builtin" : "external",
    url: server?.http_auth_type === "internal" ? "" : (server?.http_url ?? ""),
    auth:
      server?.http_auth_type === "bearer" || server?.http_auth_type === "api_key_header"
        ? server.http_auth_type
        : "none",
    token: "",
    headerName: "",
    imageModelId: server?.image_model_id ?? "",
    audience: server?.audience ?? "everyone",
    priority: server?.audience_priority ?? 100,
    groupIds: server?.user_groups?.map((group) => group.id) ?? [],
    forwardIdentity: server?.forward_identity ?? false,
    documentationUrl: server?.documentation_url ?? "",
    classificationId: server?.security_classification?.id ?? "",
    toolCatalogMaxCount: server?.tool_catalog_max_count ?? 256,
    toolCatalogMaxMiB: Math.round((server?.tool_catalog_max_bytes ?? 16777216) / 1048576),
    toolDefinitionMaxKiB: Math.round((server?.tool_definition_max_bytes ?? 65536) / 1024)
  };
}

export function sourceDraftValid(draft: SourceDraft, editing?: McpServer | null) {
  if (
    !draft.name.trim() ||
    !Number.isInteger(draft.priority) ||
    draft.priority < 0 ||
    (draft.audience === "groups" && draft.groupIds.length === 0) ||
    !Number.isInteger(draft.toolCatalogMaxCount) ||
    draft.toolCatalogMaxCount < 1 ||
    draft.toolCatalogMaxCount > 4096 ||
    !Number.isInteger(draft.toolCatalogMaxMiB) ||
    draft.toolCatalogMaxMiB < 1 ||
    draft.toolCatalogMaxMiB > 64 ||
    !Number.isInteger(draft.toolDefinitionMaxKiB) ||
    draft.toolDefinitionMaxKiB < 1 ||
    draft.toolDefinitionMaxKiB > 1024
  )
    return false;
  if (draft.source === "builtin") return Boolean(draft.imageModelId);
  if (!draft.url.trim()) return false;
  if (
    draft.auth === "bearer" &&
    !draft.token.trim() &&
    (!editing || editing.http_auth_type !== "bearer")
  )
    return false;
  if (
    draft.auth === "api_key_header" &&
    (!draft.token.trim() || !draft.headerName.trim()) &&
    (!editing || editing.http_auth_type !== "api_key_header")
  )
    return false;
  return true;
}

function credentials(draft: SourceDraft) {
  if (!draft.token.trim()) return undefined;
  if (draft.auth === "bearer") return { token: draft.token.trim() };
  if (draft.auth === "api_key_header")
    return draft.headerName.trim()
      ? { header_name: draft.headerName.trim(), token: draft.token.trim() }
      : { token: draft.token.trim() };
  return undefined;
}

/** The built-in image source activates on creation; external connections await review. */
export function createSourcePayload(
  purpose: Capability,
  draft: SourceDraft
): McpServerCreatePayload {
  return {
    name: draft.name.trim(),
    purpose,
    description: draft.description.trim() || null,
    http_auth_type: draft.source === "builtin" ? "internal" : draft.auth,
    ...(draft.source === "builtin"
      ? { image_model_id: draft.imageModelId, activate: true }
      : {
          http_url: draft.url.trim(),
          security_classification: draft.classificationId ? { id: draft.classificationId } : null
        }),
    ...(credentials(draft) ? { http_auth_config_schema: credentials(draft) } : {}),
    audience: draft.audience,
    audience_priority: draft.priority,
    user_group_ids: draft.audience === "groups" ? draft.groupIds : [],
    forward_identity: draft.forwardIdentity,
    documentation_url: draft.documentationUrl.trim() || null,
    tool_catalog_max_count: draft.toolCatalogMaxCount,
    tool_catalog_max_bytes: draft.toolCatalogMaxMiB * 1048576,
    tool_definition_max_bytes: draft.toolDefinitionMaxKiB * 1024
  };
}

/** Omit unchanged connection fields so metadata edits avoid remote validation. */
export function updateSourcePayload(server: McpServer, draft: SourceDraft): McpServerUpdatePayload {
  const authType = draft.source === "builtin" ? "internal" : draft.auth;
  return {
    name: draft.name.trim(),
    description: draft.description.trim() || null,
    ...(authType !== server.http_auth_type ? { http_auth_type: authType } : {}),
    ...(draft.source === "builtin"
      ? draft.imageModelId !== server.image_model_id
        ? { image_model_id: draft.imageModelId }
        : {}
      : {
          ...(draft.url.trim() !== server.http_url ? { http_url: draft.url.trim() } : {}),
          ...(server.http_auth_type === "internal" ? { image_model_id: null } : {}),
          security_classification: draft.classificationId ? { id: draft.classificationId } : null
        }),
    ...(credentials(draft) ? { http_auth_config_schema: credentials(draft) } : {}),
    audience: draft.audience,
    audience_priority: draft.priority,
    user_group_ids: draft.audience === "groups" ? draft.groupIds : [],
    forward_identity: draft.forwardIdentity,
    documentation_url: draft.documentationUrl.trim() || null,
    tool_catalog_max_count: draft.toolCatalogMaxCount,
    tool_catalog_max_bytes: draft.toolCatalogMaxMiB * 1048576,
    tool_definition_max_bytes: draft.toolDefinitionMaxKiB * 1024
  };
}
