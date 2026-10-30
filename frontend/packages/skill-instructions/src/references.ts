import type { components } from "@eneo/eneo-js";

type Schema = components["schemas"];
export type InstructionTarget =
  | Schema["SkillInstructionReference"]
  | Schema["FunctionInstructionReference"]
  | Schema["McpServerInstructionReference"]
  | Schema["McpToolInstructionReference"];

export type InstructionReference = {
  /** UTF-16 offsets for DOM selections; Python's codec uses code-point offsets. */
  start: number;
  end: number;
  text: string;
  label: string;
  target: InstructionTarget;
};

export const FUNCTION_PURPOSES = [
  "web_search",
  "image_generation",
  "file_analysis",
  "file_creation",
  "charts",
  "compute",
] as const satisfies readonly Schema["FunctionInstructionReference"]["purpose"][];
const link =
  /\[((?:\\[^\n]|[^\[\]\\\n])*)\]\((eneo-(?:skill|function|mcp|tool):[^)\n]*)\)/y;
const fenceMarker =
  /^[ \t]*(?:>[ \t]*)*(?:(?:[-+*]|\d+[.)])[ \t]+)?(`{3,}|~{3,})([^\n]*)/;
const uuidPattern = /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i;
const escapedPunctuation = /\\([!"#$%&'()*+,\-./:;<=>?@\[\]\\^_`{|}~])/g;

function uuid(value: string): string {
  if (!uuidPattern.test(value))
    throw new Error("Invalid Skill instruction reference");
  return value.toLowerCase();
}

function encodeSegment(value: string): string {
  return encodeURIComponent(value).replace(
    /[!'()*]/g,
    (char) => `%${char.charCodeAt(0).toString(16).toUpperCase()}`,
  );
}

function targetForUri(uri: string): InstructionTarget {
  const colon = uri.indexOf(":");
  const scheme = uri.slice(0, colon);
  const value = uri.slice(colon + 1);
  if (scheme === "eneo-skill") {
    const parts = value.split("@");
    if (parts.length !== 2)
      throw new Error("Invalid Skill instruction reference");
    return {
      kind: "skill",
      skill_id: uuid(parts[0]!),
      revision_id: uuid(parts[1]!),
    };
  }
  if (scheme === "eneo-function") {
    const purpose = FUNCTION_PURPOSES.find((item) => item === value);
    if (!purpose) throw new Error("Invalid Skill instruction reference");
    return { kind: "function", purpose };
  }
  if (scheme === "eneo-mcp")
    return { kind: "mcp_server", server_id: uuid(value) };
  const slash = value.indexOf("/");
  if (slash < 0) throw new Error("Invalid Skill instruction reference");
  const encoded = value.slice(slash + 1);
  const name = decodeURIComponent(encoded);
  if (
    !name ||
    /[\x00-\x1f\x7f]/.test(name) ||
    encodeSegment(name).toLowerCase() !== encoded.toLowerCase()
  )
    throw new Error("Invalid Skill instruction reference");
  return {
    kind: "mcp_tool",
    server_id: uuid(value.slice(0, slash)),
    tool_name: name,
  };
}

export function referenceUri(target: InstructionTarget): string {
  switch (target.kind) {
    case "skill":
      return `eneo-skill:${target.skill_id}@${target.revision_id}`;
    case "function":
      return `eneo-function:${target.purpose}`;
    case "mcp_server":
      return `eneo-mcp:${target.server_id}`;
    case "mcp_tool":
      return `eneo-tool:${target.server_id}/${encodeSegment(target.tool_name)}`;
  }
}

export function serializeReference(
  label: string,
  target: InstructionTarget,
): string {
  if (!label.trim() || /[\r\n]/.test(label))
    throw new Error("Invalid Skill instruction reference label");
  const value = `[${label.replace(/[\\[\]]/g, "\\$&")}](${referenceUri(target)})`;
  // The backend remains authoritative; the picker emits the same closed format.
  parseInstructionReferences(value);
  return value;
}

/** Mirrors the backend text codec, with common fixtures guarding the boundary. */
export function parseInstructionReferences(
  text: string,
): InstructionReference[] {
  const references: InstructionReference[] = [];
  const codeRuns = new Map<number, number>();
  const codeEnds = new Map<number, number[]>();
  for (const run of text.matchAll(/`+/g)) {
    const end = run.index + run[0].length;
    codeRuns.set(run.index, end);
    const endings = codeEnds.get(run[0].length) ?? [];
    endings.push(end);
    codeEnds.set(run[0].length, endings);
  }
  let fence: string | null = null;
  let cursor = 0;
  while (cursor < text.length) {
    if (cursor === 0 || text[cursor - 1] === "\n") {
      const newline = text.indexOf("\n", cursor);
      const end = newline < 0 ? text.length : newline + 1;
      const line = text.slice(cursor, end);
      const marker = fenceMarker.exec(line);
      if (fence !== null) {
        if (
          marker &&
          marker[1]![0] === fence[0] &&
          marker[1]!.length >= fence.length &&
          !marker[2]!.trim()
        )
          fence = null;
        cursor = end;
        continue;
      }
      if (marker) {
        fence = marker[1]!;
        cursor = end;
        continue;
      }
      if (line.startsWith("    ") || line.startsWith("\t")) {
        cursor = end;
        continue;
      }
    }
    if (text.startsWith("<!--", cursor)) {
      const end = text.indexOf("-->", cursor + 4);
      cursor = end < 0 ? text.length : end + 3;
      continue;
    }
    if (text[cursor] === "\\") {
      cursor += 2;
      continue;
    }
    if (text[cursor] === "`") {
      let runEnd = codeRuns.get(cursor) ?? cursor + 1;
      while (text[runEnd] === "`") runEnd++;
      const endings = codeEnds.get(runEnd - cursor) ?? [];
      let low = 0,
        high = endings.length;
      while (low < high) {
        const middle = (low + high) >>> 1;
        if (endings[middle]! <= runEnd) low = middle + 1;
        else high = middle;
      }
      cursor = endings[low] ?? runEnd;
      continue;
    }
    link.lastIndex = cursor;
    const match = text[cursor] === "[" ? link.exec(text) : null;
    if (!match) {
      cursor++;
      continue;
    }
    if (cursor === 0 || text[cursor - 1] !== "!") {
      const label = match[1]!.replace(escapedPunctuation, "$1");
      if (!label.trim())
        throw new Error("Invalid Skill instruction reference label");
      references.push({
        start: cursor,
        end: link.lastIndex,
        text: match[0],
        label,
        target: targetForUri(match[2]!),
      });
    }
    cursor = link.lastIndex;
  }
  return references;
}

export type ReferenceCandidate = {
  label: string;
  description: string;
  target: InstructionTarget;
  revisionNumber?: number;
  enabled?: boolean;
};
export type ReferencePage = {
  items: ReferenceCandidate[];
  nextCursor: string | null;
};
/** Catalogue adapters retain their application's authenticated API client. */
export type ReferenceCatalog = {
  key: string;
  skills: (
    query: string,
    cursor: string | null,
    signal: AbortSignal,
  ) => Promise<ReferencePage>;
  servers: (signal: AbortSignal) => Promise<ReferenceCandidate[]>;
  tools: (
    serverId: string,
    signal: AbortSignal,
  ) => Promise<ReferenceCandidate[]>;
  preview: (
    candidate: ReferenceCandidate,
    signal: AbortSignal,
  ) => Promise<string>;
};

export function skillCandidates(
  items: Schema["SkillSparse"][],
  currentId?: string,
): ReferenceCandidate[] {
  return items
    .filter((item) => item.id !== currentId && item.is_active)
    .map((item) => ({
      label: item.display_name,
      description: item.description,
      revisionNumber: item.current_revision_number,
      target: {
        kind: "skill",
        skill_id: item.id,
        revision_id: item.current_revision_id,
      },
    }));
}

export function publishedCandidates(
  items: Schema["PublishedSkillSummaryPublic"][],
  currentId?: string,
): ReferenceCandidate[] {
  return items
    .filter((item) => item.id !== currentId && !item.execution_blocked)
    .map((item) => ({
      label: item.display_name,
      description: item.description,
      revisionNumber: item.revision_number,
      target: {
        kind: "skill",
        skill_id: item.id,
        revision_id: item.revision_id,
      },
    }));
}

export function serverCandidates(
  items: Schema["MCPServerPublic"][],
): ReferenceCandidate[] {
  return items
    .filter((item) => item.purpose === "general")
    .map((item) => ({
      label: item.name,
      description: item.description ?? "",
      enabled: item.is_enabled,
      target: { kind: "mcp_server", server_id: item.id },
    }));
}

export function toolCandidates(
  items: Schema["MCPServerToolPublic"][],
): ReferenceCandidate[] {
  return items
    .filter(
      (item) =>
        !item.removed_from_remote &&
        (!item.requires_approval ||
          item.description != null ||
          item.input_schema != null),
    )
    .map((item) => ({
      label: item.display_name ?? item.title ?? item.name,
      description: item.description ?? "",
      enabled: item.is_enabled_by_default,
      target: {
        kind: "mcp_tool",
        server_id: item.mcp_server_id,
        tool_name: item.name,
      },
    }));
}

/** Explains why a helper may run even when its independent selection is off. */
export function dependencySources(
  bindings: Pick<
    Schema["SkillBindingSummary"],
    "skill_id" | "display_name" | "dependencies"
  >[],
): Map<string, string[]> {
  const sources = new Map<string, string[]>();
  for (const binding of bindings)
    for (const helper of binding.dependencies ?? []) {
      const names = sources.get(helper.skill_id) ?? [];
      names.push(binding.display_name);
      sources.set(helper.skill_id, names);
    }
  return sources;
}

/** Read-only preview: keep the instruction text and show reference labels. */
export function readableInstructions(text: string): string {
  const parts: string[] = [];
  let cursor = 0;
  for (const reference of parseInstructionReferences(text)) {
    parts.push(text.slice(cursor, reference.start), `[${reference.label}]`);
    cursor = reference.end;
  }
  return parts.join("") + text.slice(cursor);
}
