/**
 * Turn a raw tool identifier into a readable label: drop a server/ prefix,
 * swap separators for spaces, and capitalize. `search_knowledge_base` →
 * `Search knowledge base`, `jira/create_issue` → `Jira create issue`.
 */
export function humanizeToolName(name: string): string {
  const words = name.replace(/[/_-]+/g, " ").trim();
  if (!words) return name;
  return words.charAt(0).toUpperCase() + words.slice(1);
}

type Translate = (key: string, values?: Record<string, string | number>) => string;

/** A file attached to the conversation or its assistant, as the session lists them. */
export type AttachedFile = { id: string; name: string };
type ToolLike = {
  toolName: string;
  input?: unknown;
  /** Set on parts mapped from a saved session (map-session.ts). */
  providerMetadata?: unknown;
  /** AI SDK v6 keeps a streamed tool's metadata here (input phase)… */
  callProviderMetadata?: unknown;
  /** …and here (output phase). */
  resultProviderMetadata?: unknown;
};

/**
 * The `eneo` provider metadata of a tool part (server_name, title, purpose,
 * approved), wherever the AI SDK put it: saved sessions use
 * `providerMetadata`, live streams `callProviderMetadata` /
 * `resultProviderMetadata`.
 */
export function eneoToolMetadata(part: ToolLike): Record<string, unknown> {
  for (const provider of [
    part.providerMetadata,
    part.callProviderMetadata,
    part.resultProviderMetadata
  ]) {
    const eneo =
      provider && typeof provider === "object" && "eneo" in provider
        ? (provider as { eneo?: unknown }).eneo
        : null;
    if (eneo && typeof eneo === "object") return eneo as Record<string, unknown>;
  }
  return {};
}

/**
 * Whether a tool call ran on Eneo's own server of that name. The backend
 * stamps `is_internal` from the server the call was routed to, so an external
 * server an admin named "files", "knowledge" or "skills" does not borrow the
 * built-in labels. Rows persisted before the flag existed carry none and fall
 * back to the name.
 */
function isOwnServer(isInternal: unknown): boolean {
  return isInternal !== false;
}

function metadata(part: ToolLike): {
  serverName: string;
  title: string | null;
  purpose: string | null;
  /** The server is one of Eneo's own, judging by the backend's flag (or the name when it carries none). */
  ownServer: boolean;
} {
  const values = eneoToolMetadata(part);
  const server = "server_name" in values ? values.server_name : null;
  const title = "title" in values ? values.title : null;
  const purpose = "purpose" in values ? values.purpose : null;
  return {
    serverName: typeof server === "string" ? server : "",
    title: typeof title === "string" ? title : null,
    purpose: typeof purpose === "string" ? purpose : null,
    ownServer: isOwnServer(values.is_internal)
  };
}

function argumentsOf(part: ToolLike): Record<string, unknown> {
  return part.input && typeof part.input === "object" && !Array.isArray(part.input)
    ? (part.input as Record<string, unknown>)
    : {};
}

function searchQuery(args: Record<string, unknown>): string | null {
  const value = args.query ?? args.q;
  if (typeof value !== "string") return null;
  const query = value.trim();
  return query ? (query.length > 60 ? `${query.slice(0, 60)}…` : query) : null;
}

/** Whether a tool call is a Skill activation step rather than a call to a server named "skills". */
export function isSkillCall(part: ToolLike): boolean {
  const { serverName, ownServer } = metadata(part);
  return serverName === "skills" && ownServer;
}

export function skillName(part: ToolLike): string {
  return metadata(part).title ?? humanizeToolName(part.toolName);
}

/** Human-facing names for Eneo tools and capability calls; external MCP titles stay intact. */
export function toolPresentation(part: ToolLike, t: Translate, done: boolean) {
  const { serverName, title, purpose, ownServer } = metadata(part);
  const args = argumentsOf(part);
  const query = searchQuery(args);
  if (isSkillCall(part)) {
    return { label: t("tool_activate_skill", { name: skillName(part) }), server: t("skills") };
  }

  const suffix = done ? "_done" : "";
  if (ownServer && serverName === "knowledge") {
    const key: Record<string, string> = {
      search_knowledge: query
        ? `tool_search_knowledge_query${suffix}`
        : `tool_search_knowledge${suffix}`,
      list_knowledge_sources: `tool_list_knowledge_sources${suffix}`,
      read_source: `tool_read_source${suffix}`,
      describe_source: `tool_describe_source${suffix}`
    };
    const label = key[part.toolName];
    if (label) return { label: t(label, query ? { query } : undefined), server: t("knowledge") };
  }
  if (ownServer && serverName === "files" && part.toolName === "read_file") {
    return { label: t(`tool_read_file${suffix}`), server: t("internal_files_server") };
  }
  if (purpose === "web_search") {
    return {
      label: t(
        query ? `tool_web_search_query${suffix}` : `tool_web_search${suffix}`,
        query ? { query } : undefined
      ),
      server: t("web_search"),
      provider: serverName && serverName !== "web_search" ? serverName : null
    };
  }
  if (purpose === "image_generation" || (ownServer && serverName === "image_generation")) {
    const editing = Array.isArray(args.reference_images) && args.reference_images.length > 0;
    return {
      label: t(`tool_${editing ? "edit" : "generate"}_image${suffix}`),
      server: t("image_generation"),
      // An external provider's own name stays visible; Eneo's built-in one does not.
      provider: serverName && !(ownServer && serverName === "image_generation") ? serverName : null
    };
  }
  return {
    label: title ?? humanizeToolName(part.toolName),
    server: serverName || null,
    provider: null
  };
}

const FILE_URL_ID = /\/files\/([0-9a-f-]{36})\//i;

/** The file id in one of Eneo's signed download urls (`…/api/v1/files/<id>/…`). */
export function fileIdFromUrl(url: unknown): string | null {
  if (typeof url !== "string") return null;
  return FILE_URL_ID.exec(url)?.[1] ?? null;
}

const SCALAR_MAX = 48;

/** Scalar arguments as "key: value", long strings cut: the generic target of a call. */
export function readableArguments(args: Record<string, unknown>): string | null {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(args)) {
    if (value == null || typeof value === "object") continue;
    const text = String(value);
    parts.push(`${key}: ${text.length > SCALAR_MAX ? `${text.slice(0, SCALAR_MAX)}…` : text}`);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

/**
 * What a call acted on, for the row under its label: the file and position
 * for a read of an attachment, the query for a search, else the readable
 * arguments. A signed download url never shows; the attachment's name does.
 */
export function toolTarget(
  part: ToolLike,
  t: Translate,
  { files = [], locale = "sv" }: { files?: AttachedFile[]; locale?: string } = {}
): string | null {
  const { serverName, purpose, ownServer } = metadata(part);
  const args = argumentsOf(part);
  const query = searchQuery(args);
  if (ownServer && serverName === "files" && part.toolName === "read_file") {
    const id = fileIdFromUrl(args.url);
    const name = files.find((file) => file.id === id)?.name ?? t("internal_files_server");
    const offset = typeof args.offset === "number" ? args.offset : 0;
    const position =
      offset > 0
        ? t("chat_tool_read_from", { offset: new Intl.NumberFormat(locale).format(offset) })
        : t("chat_tool_read_from_start");
    return `${name} · ${position}`;
  }
  if (query && (purpose === "web_search" || (ownServer && serverName === "knowledge"))) {
    return query;
  }
  return readableArguments(args);
}
