import type { ResourcePermission, Space } from "../space";

/** Test-only: a space object as the API returns it, with overridable parts. */

const ALL: ResourcePermission[] = ["read", "create", "edit", "delete", "add", "publish"];

function list<T>(items: T[] = [], permissions: ResourcePermission[] = ALL) {
  return { items, count: items.length, permissions };
}

export type SpaceFixtureOptions = {
  permissions?: ResourcePermission[];
  assistants?: unknown[];
  groupChats?: unknown[];
  apps?: unknown[];
  services?: unknown[];
  collections?: unknown[];
  websites?: unknown[];
  integrations?: unknown[];
  members?: unknown[];
  /** Permissions for every resource list (assistants, knowledge, members…). */
  resourcePermissions?: ResourcePermission[];
  skillPermissions?: ResourcePermission[];
  overrides?: Record<string, unknown>;
};

export function makeSpace(options: SpaceFixtureOptions = {}): Space {
  const resource = options.resourcePermissions ?? ALL;
  return {
    id: "space-1",
    name: "Upphandling",
    description: "Stöd för kommunens upphandlare.",
    personal: false,
    organization: false,
    icon_id: null,
    created_at: "2026-03-12T09:00:00Z",
    updated_at: "2026-09-01T09:00:00Z",
    permissions: options.permissions ?? ["read", "edit", "delete"],
    applications: {
      assistants: list(options.assistants, resource),
      group_chats: list(options.groupChats, resource),
      services: list(options.services, resource),
      apps: list(options.apps, resource)
    },
    default_assistant: { id: "default-assistant", name: "Eneo", permissions: ["read"] },
    embedding_models: [
      { id: "embed-1", name: "multilingual-e5-large", nickname: null, is_deprecated: false }
    ],
    completion_models: [
      { id: "model-1", name: "claude-haiku", nickname: "Haiku 4.5" },
      { id: "model-2", name: "claude-opus", nickname: null }
    ],
    transcription_models: [],
    knowledge: {
      groups: list(options.collections, resource),
      websites: list(options.websites, resource),
      integration_knowledge_list: list(options.integrations, resource)
    },
    members: list(options.members, resource),
    group_members: list([], resource),
    skill_permissions: options.skillPermissions ?? ["read", "create", "edit", "delete"],
    available_roles: [
      { value: "admin", label: "Admin" },
      { value: "editor", label: "Editor" },
      { value: "viewer", label: "Viewer" }
    ],
    security_classification: null,
    ...options.overrides
  } as unknown as Space;
}

export function makeCollection(overrides: Record<string, unknown> = {}) {
  return {
    id: "collection-1",
    name: "Upphandlingspolicy",
    space_id: "space-1",
    permissions: ["read", "edit", "delete"],
    embedding_model: { id: "embed-1", name: "multilingual-e5-large" },
    metadata: { num_info_blobs: 42, size: 1000 },
    created_at: "2026-08-01T08:00:00Z",
    updated_at: "2026-09-20T08:12:00Z",
    ...overrides
  };
}

export function makeWebsite(overrides: Record<string, unknown> = {}) {
  return {
    id: "website-1",
    name: null,
    url: "https://www.upphandlingsmyndigheten.se",
    space_id: "space-1",
    permissions: ["read", "edit", "delete"],
    embedding_model: { id: "embed-1", name: "multilingual-e5-large" },
    metadata: { size: 1000 },
    update_interval: "weekly",
    crawl_type: "crawl",
    download_files: false,
    requires_http_auth: false,
    is_auto_disabled: false,
    latest_crawl: {
      id: "crawl-1",
      status: "complete",
      pages_crawled: 318,
      files_downloaded: 0,
      pages_failed: 0,
      files_failed: 0,
      result_location: null,
      created_at: "2026-09-10T08:00:00Z",
      finished_at: "2026-09-10T09:00:00Z"
    },
    created_at: "2026-08-01T08:00:00Z",
    updated_at: "2026-08-01T08:00:00Z",
    ...overrides
  };
}

export function makeAssistant(overrides: Record<string, unknown> = {}) {
  return {
    id: "assistant-1",
    type: "assistant",
    name: "Upphandlingsassistenten",
    description: "Svarar på frågor om LOU.",
    published: true,
    user_id: "user-1",
    permissions: ["read", "edit", "delete", "publish"],
    completion_model_id: "model-1",
    icon_id: null,
    created_at: "2026-08-01T08:00:00Z",
    updated_at: "2026-09-01T08:00:00Z",
    ...overrides
  };
}

export function makeMember(overrides: Record<string, unknown> = {}) {
  return {
    id: "user-1",
    email: "anna.lind@example.com",
    username: null,
    role: "admin",
    ...overrides
  };
}
