import type {
  ApiKey,
  ApiKeyCreateRequest,
  ApiKeyCreationConstraints,
  ApiKeyOwnership,
  ApiKeyPermission,
  ApiKeyScopeType,
  ApiKeyType,
  ApiKeyUpdateRequest,
  ResourcePermissionLevel
} from "./api-keys";

/*
 * What the API key form holds and the rules it checks before sending. The
 * checks are a convenience that names a problem at its field; the backend's
 * key policy (api_key_policy.py) is what enforces them.
 */

export const RESOURCE_KEYS = [
  "assistants",
  "apps",
  "spaces",
  "knowledge",
  "conversations",
  "files",
  "jobs",
  "prompts"
] as const;
export type ResourceKey = (typeof RESOURCE_KEYS)[number];
export type ResourcePermissions = Record<ResourceKey, ResourcePermissionLevel>;

export const RESOURCE_LEVELS: ResourcePermissionLevel[] = ["none", "read", "write", "admin"];

/**
 * The resource types a scope grants access to. Keep in sync with the backend's
 * `_SCOPE_RESOURCE_PERMISSION_FIELDS` (api_key_policy.py): drift shows as a 400
 * on submit. The others are sent as "none".
 */
const SCOPE_RESOURCE_KEYS: Record<ApiKeyScopeType, readonly ResourceKey[]> = {
  tenant: RESOURCE_KEYS,
  space: RESOURCE_KEYS,
  assistant: ["assistants", "conversations", "files"],
  app: ["apps", "files"]
};

/** Public keys never reach jobs or prompts (the backend refuses them). */
const PUBLIC_KEY_HIDDEN: ReadonlySet<ResourceKey> = new Set(["jobs", "prompts"]);

/** A key scoped to one assistant or app always reaches that assistant or app. */
function requiredResource(scopeType: ApiKeyScopeType): ResourceKey | null {
  if (scopeType === "assistant") return "assistants";
  if (scopeType === "app") return "apps";
  return null;
}

export type ApiKeyDraft = {
  name: string;
  description: string;
  keyType: ApiKeyType;
  ownership: ApiKeyOwnership;
  scopeType: ApiKeyScopeType;
  /** The resource picked from the list. */
  scopeId: string | null;
  /** A resource id typed by hand; it wins over the pick. */
  manualScopeId: string;
  resourcePermissions: ResourcePermissions;
  allowedOrigins: string[];
  allowedIps: string[];
  /** An instant (ISO), or null for no expiry. */
  expiresAt: string | null;
  /** As typed; empty means the tenant default. */
  rateLimit: string;
};

function allAt(level: ResourcePermissionLevel): ResourcePermissions {
  return Object.fromEntries(RESOURCE_KEYS.map((key) => [key, level])) as ResourcePermissions;
}

/** A public key starts out reading assistants and apps only. */
const PUBLIC_KEY_DEFAULTS: ResourcePermissions = {
  ...allAt("none"),
  assistants: "read",
  apps: "read"
};

export function newApiKeyDraft({
  scopeType = "tenant",
  scopeId = null,
  ownership = "user"
}: {
  scopeType?: ApiKeyScopeType;
  scopeId?: string | null;
  ownership?: ApiKeyOwnership;
} = {}): ApiKeyDraft {
  return {
    name: "",
    description: "",
    keyType: "sk_",
    ownership,
    scopeType,
    scopeId,
    manualScopeId: "",
    resourcePermissions: allAt("read"),
    allowedOrigins: [],
    allowedIps: [],
    expiresAt: null,
    rateLimit: ""
  };
}

/** An existing key as the edit form shows it (type, ownership and scope stay fixed). */
export function draftFromApiKey(key: ApiKey): ApiKeyDraft {
  const stored = key.resource_permissions;
  const resourcePermissions: ResourcePermissions = stored
    ? (Object.fromEntries(
        RESOURCE_KEYS.map((resource) => [resource, levelOf(stored[resource])])
      ) as ResourcePermissions)
    : key.key_type === "pk_"
      ? PUBLIC_KEY_DEFAULTS
      : allAt(key.permission);
  return {
    name: key.name,
    description: key.description ?? "",
    keyType: key.key_type,
    ownership: key.ownership ?? "user",
    scopeType: key.scope_type,
    scopeId: key.scope_id ?? null,
    manualScopeId: "",
    resourcePermissions,
    allowedOrigins: key.allowed_origins ?? [],
    allowedIps: key.allowed_ips ?? [],
    expiresAt: key.expires_at ?? null,
    rateLimit: key.rate_limit?.toString() ?? ""
  };
}

function levelOf(value: string | undefined): ResourcePermissionLevel {
  return RESOURCE_LEVELS.includes(value as ResourcePermissionLevel)
    ? (value as ResourcePermissionLevel)
    : "none";
}

/** A new key type resets the access to that type's defaults. */
export function withKeyType(draft: ApiKeyDraft, keyType: ApiKeyType): ApiKeyDraft {
  return {
    ...draft,
    keyType,
    resourcePermissions: keyType === "pk_" ? PUBLIC_KEY_DEFAULTS : allAt("read")
  };
}

/** A new scope type forgets the picked resource. */
export function withScopeType(draft: ApiKeyDraft, scopeType: ApiKeyScopeType): ApiKeyDraft {
  return { ...draft, scopeType, scopeId: null, manualScopeId: "" };
}

/** The resource types the form shows for the draft's scope and key type. */
export function visibleResources(draft: Pick<ApiKeyDraft, "scopeType" | "keyType">): ResourceKey[] {
  return SCOPE_RESOURCE_KEYS[draft.scopeType].filter(
    (key) => draft.keyType !== "pk_" || !PUBLIC_KEY_HIDDEN.has(key)
  );
}

/** Which levels a resource offers: a public key reads at most; the scoped resource is never "none". */
export function isLevelAllowed(
  draft: Pick<ApiKeyDraft, "scopeType" | "keyType">,
  key: ResourceKey,
  level: ResourcePermissionLevel
): boolean {
  if (key === requiredResource(draft.scopeType) && level === "none") return false;
  return draft.keyType !== "pk_" || level === "none" || level === "read";
}

/** The level the key gets for a resource: what is set, within what the scope and type allow. */
export function resourceLevel(draft: ApiKeyDraft, key: ResourceKey): ResourcePermissionLevel {
  if (!visibleResources(draft).includes(key)) return "none";
  const level = draft.resourcePermissions[key];
  if (isLevelAllowed(draft, key, level)) return level;
  return key === requiredResource(draft.scopeType) ? "read" : "none";
}

function resourcePermissionsBody(draft: ApiKeyDraft): ResourcePermissions {
  return Object.fromEntries(
    RESOURCE_KEYS.map((key) => [key, resourceLevel(draft, key)])
  ) as ResourcePermissions;
}

/** The key's overall ceiling: its highest resource level (a public key only reads). */
export function effectivePermission(draft: ApiKeyDraft): ApiKeyPermission {
  if (draft.keyType === "pk_") return "read";
  const levels = RESOURCE_KEYS.map((key) => resourceLevel(draft, key));
  if (levels.includes("admin")) return "admin";
  if (levels.includes("write")) return "write";
  return "read";
}

/** The resource the key is scoped to; null for the whole organization. */
export function draftScopeId(draft: ApiKeyDraft): string | null {
  if (draft.scopeType === "tenant") return null;
  return draft.manualScopeId.trim() || draft.scopeId || null;
}

const WILDCARD_ORIGIN = /^https?:\/\/(\*|[\w.-]+\*?|\*\.[\w.-]+)(:\d+|:\*)?$/;

/** Why an allowed origin cannot be used, as a message key; null when it can. */
export function originProblem(value: string): string | null {
  if (value.includes("*")) {
    return WILDCARD_ORIGIN.test(value) ? null : "api_keys_tag_invalid_wildcard";
  }
  try {
    const url = new URL(value);
    const web = url.protocol === "http:" || url.protocol === "https:";
    return web && url.hostname ? null : "api_keys_tag_invalid_origin";
  } catch {
    return "api_keys_tag_invalid_origin";
  }
}

const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})(?:\/(\d{1,2}))?$/;
const IPV6 = /^(?=(?:[^:]*:){2})[0-9a-fA-F:.]+(?:\/(\d{1,3}))?$/;

/** Why an allowed IP or range cannot be used, as a message key; null when it can. */
export function ipProblem(value: string): string | null {
  const v4 = IPV4.exec(value);
  if (v4) {
    if (v4.slice(1, 5).some((octet) => Number(octet) > 255)) return "api_keys_tag_invalid_octet";
    if (v4[5] !== undefined && Number(v4[5]) > 32) return "api_keys_tag_invalid_cidr";
    return null;
  }
  const v6 = IPV6.exec(value);
  if (v6 && (v6[1] === undefined || Number(v6[1]) <= 128)) return null;
  return "api_keys_tag_invalid_ip";
}

/** The first problem in a list of origins or IPs, with the entry it is about. */
export function listProblem(
  values: string[],
  problemOf: (value: string) => string | null
): { key: string; value: string } | null {
  for (const value of values) {
    const key = problemOf(value);
    if (key) return { key, value };
  }
  return null;
}

export type DraftField = "name" | "scope" | "origins" | "ips" | "expiry" | "rateLimit";
export type DraftProblems = Partial<Record<DraftField, string>>;

/**
 * What stops the draft from being sent, per field, in the order the form
 * shows them. `t` translates (next-intl's, or a stub in tests).
 */
export function draftProblems(
  draft: ApiKeyDraft,
  {
    mode,
    constraints
  }: { mode: "create" | "edit"; constraints: ApiKeyCreationConstraints | undefined },
  t: (key: string, values?: Record<string, string | number>) => string
): DraftProblems {
  const problems: DraftProblems = {};
  if (!draft.name.trim()) problems.name = t("api_keys_name_required");
  if (mode === "create" && draft.scopeType !== "tenant" && !draftScopeId(draft)) {
    problems.scope = t("api_keys_select_scope", {
      scopeType: t(`api_keys_scope_${draft.scopeType}`).toLocaleLowerCase()
    });
  }
  if (draft.keyType === "pk_") {
    const invalid = listProblem(draft.allowedOrigins, originProblem);
    if (draft.allowedOrigins.length === 0) problems.origins = t("api_keys_origin_required");
    else if (invalid) problems.origins = `${invalid.value}: ${t(invalid.key)}`;
  } else {
    const invalid = listProblem(draft.allowedIps, ipProblem);
    if (invalid) problems.ips = `${invalid.value}: ${t(invalid.key)}`;
  }
  if (mode === "create" && constraints?.require_expiration && !draft.expiresAt) {
    problems.expiry = t("api_keys_exp_required");
  }
  const rate = draft.rateLimit.trim();
  if (rate) {
    const value = Number(rate);
    const max = constraints?.max_rate_limit;
    if (!Number.isInteger(value) || value < 1)
      problems.rateLimit = t("api_keys_rate_limit_invalid");
    else if (max != null && value > max) problems.rateLimit = t("api_keys_rate_limit_max", { max });
  }
  return problems;
}

function rateLimitBody(draft: ApiKeyDraft): number | null {
  return draft.rateLimit.trim() ? Number(draft.rateLimit) : null;
}

/** The create request for a draft without problems. */
export function createRequest(draft: ApiKeyDraft): ApiKeyCreateRequest {
  return {
    name: draft.name.trim(),
    description: draft.description.trim() || null,
    key_type: draft.keyType,
    permission: effectivePermission(draft),
    scope_type: draft.scopeType,
    scope_id: draftScopeId(draft),
    ownership: draft.ownership,
    allowed_origins: draft.keyType === "pk_" ? draft.allowedOrigins : null,
    allowed_ips: draft.keyType === "sk_" && draft.allowedIps.length > 0 ? draft.allowedIps : null,
    expires_at: draft.expiresAt,
    rate_limit: rateLimitBody(draft),
    resource_permissions: resourcePermissionsBody(draft)
  };
}

const sameList = (a: readonly string[], b: readonly string[]) =>
  a.length === b.length && a.every((value, index) => value === b[index]);

/**
 * The update request for what the draft changed on `key`; empty when nothing
 * did. Type, ownership, scope and expiry are not edited here, and with
 * `metadataOnly` (a revoked or expired key) only the name and description.
 */
export function updateRequest(
  draft: ApiKeyDraft,
  key: ApiKey,
  { metadataOnly = false }: { metadataOnly?: boolean } = {}
): ApiKeyUpdateRequest {
  const update: ApiKeyUpdateRequest = {};
  const name = draft.name.trim();
  if (name !== key.name) update.name = name;
  const description = draft.description.trim();
  if (description !== (key.description ?? "")) update.description = description || null;
  if (metadataOnly) return update;
  const rateLimit = rateLimitBody(draft);
  if (rateLimit !== (key.rate_limit ?? null)) update.rate_limit = rateLimit;
  const permissions = resourcePermissionsBody(draft);
  const stored = key.resource_permissions;
  if (
    !stored ||
    RESOURCE_KEYS.some((resource) => levelOf(stored[resource]) !== permissions[resource])
  ) {
    update.resource_permissions = permissions;
  }
  if (key.key_type === "pk_" && !sameList(draft.allowedOrigins, key.allowed_origins ?? [])) {
    update.allowed_origins = draft.allowedOrigins;
  }
  if (key.key_type === "sk_" && !sameList(draft.allowedIps, key.allowed_ips ?? [])) {
    update.allowed_ips = draft.allowedIps.length > 0 ? draft.allowedIps : null;
  }
  return update;
}
