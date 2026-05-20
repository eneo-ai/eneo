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
