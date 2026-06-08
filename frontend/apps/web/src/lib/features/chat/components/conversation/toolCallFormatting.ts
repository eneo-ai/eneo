/*
    Copyright (c) 2024 Sundsvalls Kommun

    Licensed under the MIT License.
*/

/**
 * Decode JSON-style escape sequences (`\n`, `\"`, `\\`, `\t`, `\r`)
 * that arrive as LITERAL characters in tool-call argument strings.
 *
 * Some LLM tool-call serializations send string values pre-escaped (the
 * JSON inside the JSON), so the eneo backend ends up with a string whose
 * raw bytes are `S E L E C T \ n F R O M`. Rendering that verbatim shows
 * the user `\n` literally. We collapse the common escapes in one pass —
 * if no escape sequences are present, the input is returned unchanged.
 */
export function decodeEscapes(value: string): string {
  if (!/\\[nrt"\\]/.test(value)) return value;
  return value.replace(/\\(["\\nrt])/g, (_, c) => {
    if (c === "n") return "\n";
    if (c === "r") return "\r";
    if (c === "t") return "\t";
    return c;
  });
}

/**
 * Per-arg value formatter. Strings come back already-decoded; non-string
 * scalars are JSON-stringified compactly; nested objects are pretty-printed.
 * The caller renders each entry in its own block with a separate key label,
 * so this returns just the value body (no `key:` prefix, no trailing newline).
 */
export function formatToolArgValue(value: unknown): string {
  if (typeof value === "string") return decodeEscapes(value);
  if (value === null || typeof value !== "object") return JSON.stringify(value);
  return JSON.stringify(value, null, 2);
}

/**
 * Render a tool-call's argument map as a single object literal so it reads as
 * structured input rather than loose labelled text:
 *
 *   {
 *     text: "Du är en kockassistent...",
 *     description: "Uppdaterad roll..."
 *   }
 *
 * String values keep their real newlines (escape-decoded) inside the quotes so
 * a long value (a system prompt) stays readable instead of one escaped line.
 */
export function formatToolArgs(args: Record<string, unknown>): string {
  const entries = Object.entries(args);
  if (entries.length === 0) return "{}";
  const lines = entries.map(([key, value]) => {
    const formatted =
      typeof value === "string" ? `"${decodeEscapes(value)}"` : JSON.stringify(value, null, 2);
    return `  ${key}: ${formatted}`;
  });
  return `{\n${lines.join(",\n")}\n}`;
}

// Primary "content" field of a config-change capability, in priority order.
// Each capability sets at most one of these as its meaningful value (e.g. the
// new system prompt is `text`; a name change is `name`). Secondary/meta fields
// (a prompt-version `description` label, internal ids) are skipped.
const PRIMARY_CONTENT_FIELDS = [
  "text",
  "content",
  "prompt",
  "instructions",
  "body",
  "message",
  "name",
  "description"
];

/**
 * Preview of the change a user is being asked to confirm: just the primary
 * content value (the new prompt/name/...), not the raw tool-call envelope. The
 * tool-call JSON (field names, version labels) is an implementation detail the
 * user doesn't need. Falls back to the structured view when there is no plain
 * string content to show (e.g. id lists, booleans).
 */
export function formatToolChangePreview(args: Record<string, unknown>): string {
  const strings = Object.entries(args).filter(
    ([, v]) => typeof v === "string" && v.trim().length > 0
  ) as [string, string][];
  if (strings.length === 0) return formatToolArgs(args);

  for (const field of PRIMARY_CONTENT_FIELDS) {
    const match = strings.find(([key]) => key.toLowerCase() === field);
    if (match) return decodeEscapes(match[1]);
  }
  // No known field name — show the longest string value (the most substantive).
  const longest = strings.reduce((a, b) => (b[1].length > a[1].length ? b : a));
  return decodeEscapes(longest[1]);
}

/**
 * Render a tool-call result. JSON payloads are pretty-printed; anything else is
 * shown as escape-decoded text.
 */
export function formatToolResult(result: string): string {
  const trimmed = result.trim();
  if (trimmed.startsWith("{") || trimmed.startsWith("[")) {
    try {
      return JSON.stringify(JSON.parse(trimmed), null, 2);
    } catch {
      // Not valid JSON — fall through to the plain-text rendering.
    }
  }
  return decodeEscapes(result);
}
