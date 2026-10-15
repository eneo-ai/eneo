const SPACE = /\s/;

function skipSpace(text: string, from: number): number {
  let i = from;
  while (i < text.length && SPACE.test(text[i])) i++;
  return i;
}

const ESCAPES: Record<string, string> = {
  '"': '"',
  "\\": "\\",
  "/": "/",
  b: "\b",
  f: "\f",
  n: "\n",
  r: "\r",
  t: "\t"
};

/**
 * Reads the JSON string that opens at `start`. A string the text ends inside
 * is returned as far as it goes: an escape cut in half is left out, and so is
 * the first half of a surrogate pair whose second half has not arrived.
 */
function readString(text: string, start: number): { value: string; end: number; closed: boolean } {
  let value = "";
  let i = start + 1;
  let plainFrom = i;
  while (i < text.length) {
    const char = text[i];
    if (char === '"') {
      return { value: value + text.slice(plainFrom, i), end: i + 1, closed: true };
    }
    if (char !== "\\") {
      i++;
      continue;
    }
    value += text.slice(plainFrom, i);
    const escaped = text[i + 1];
    if (escaped === undefined) return { value, end: text.length, closed: false };
    if (escaped === "u") {
      const hex = text.slice(i + 2, i + 6);
      if (hex.length < 4) return { value, end: text.length, closed: false };
      value += String.fromCharCode(Number.parseInt(hex, 16));
      i += 6;
    } else {
      value += ESCAPES[escaped] ?? escaped;
      i += 2;
    }
    plainFrom = i;
  }
  value += text.slice(plainFrom);
  const last = value.charCodeAt(value.length - 1);
  if (last >= 0xd800 && last <= 0xdbff) value = value.slice(0, -1);
  return { value, end: text.length, closed: false };
}

/** The index after the value at `start`, or -1 when the text ends inside it. */
function skipValue(text: string, start: number): number {
  const opener = text[start];
  if (opener === "{" || opener === "[") {
    let depth = 0;
    let i = start;
    while (i < text.length) {
      const char = text[i];
      if (char === '"') {
        const string = readString(text, i);
        if (!string.closed) return -1;
        i = string.end;
        continue;
      }
      if (char === "{" || char === "[") depth++;
      else if (char === "}" || char === "]") {
        depth--;
        if (depth === 0) return i + 1;
      }
      i++;
    }
    return -1;
  }
  // A number or a literal ends at the next delimiter; without one it may be cut.
  let i = start;
  while (i < text.length && !/[,}\]\s]/.test(text[i])) i++;
  return i < text.length ? i : -1;
}

/**
 * The top-level string values of a JSON object that is still being written.
 *
 * A tool call's arguments arrive as raw JSON text, cut anywhere. A value that
 * is not finished yet is returned as far as it goes, so the text of a document
 * can be shown while the model writes it. Values of other types are skipped.
 */
export function readPartialStringArguments(text: string): Record<string, string> {
  const values: Record<string, string> = {};
  let i = skipSpace(text, 0);
  if (text[i] !== "{") return values;
  i = skipSpace(text, i + 1);
  for (;;) {
    if (text[i] === ",") i = skipSpace(text, i + 1);
    if (text[i] !== '"') return values;
    const key = readString(text, i);
    if (!key.closed) return values;
    i = skipSpace(text, key.end);
    if (text[i] !== ":") return values;
    i = skipSpace(text, i + 1);
    if (i >= text.length) return values;
    if (text[i] === '"') {
      const value = readString(text, i);
      values[key.value] = value.value;
      if (!value.closed) return values;
      i = value.end;
    } else {
      i = skipValue(text, i);
      if (i === -1) return values;
    }
    i = skipSpace(text, i);
  }
}

type Read = { value: unknown; end: number; complete: boolean };

/**
 * Reads the JSON value at `start` as far as the text goes. Null when nothing
 * of it can be kept yet: a number or literal the text may still extend.
 */
function readValue(text: string, start: number): Read | null {
  const opener = text[start];
  if (opener === '"') {
    const string = readString(text, start);
    return { value: string.value, end: string.end, complete: string.closed };
  }
  if (opener === "{") return readObject(text, start);
  if (opener === "[") return readArray(text, start);
  let i = start;
  while (i < text.length && !/[,}\]\s]/.test(text[i])) i++;
  if (i >= text.length) return null;
  try {
    return { value: JSON.parse(text.slice(start, i)), end: i, complete: true };
  } catch {
    return null;
  }
}

function readObject(text: string, start: number): Read {
  const value: Record<string, unknown> = {};
  const cut: Read = { value, end: text.length, complete: false };
  let i = skipSpace(text, start + 1);
  for (;;) {
    if (text[i] === "}") return { value, end: i + 1, complete: true };
    if (text[i] === ",") {
      i = skipSpace(text, i + 1);
      continue;
    }
    if (text[i] !== '"') return cut;
    const key = readString(text, i);
    if (!key.closed) return cut;
    i = skipSpace(text, key.end);
    if (text[i] !== ":") return cut;
    i = skipSpace(text, i + 1);
    const read = i < text.length ? readValue(text, i) : null;
    if (!read) return cut;
    value[key.value] = read.value;
    if (!read.complete) return cut;
    i = skipSpace(text, read.end);
  }
}

function readArray(text: string, start: number): Read {
  const value: unknown[] = [];
  const cut: Read = { value, end: text.length, complete: false };
  let i = skipSpace(text, start + 1);
  for (;;) {
    if (text[i] === "]") return { value, end: i + 1, complete: true };
    if (text[i] === ",") {
      i = skipSpace(text, i + 1);
      continue;
    }
    const read = i < text.length ? readValue(text, i) : null;
    if (!read) return cut;
    value.push(read.value);
    if (!read.complete) return cut;
    i = skipSpace(text, read.end);
  }
}

/**
 * The arguments of a tool call that is still being written, nested values
 * included, as far as they can be read.
 *
 * A string is kept as far as it goes and so are the entries of an object or
 * a list; a number or literal the text may still extend is left out until it
 * is finished. The result is always a valid object, which is what a tool's
 * interactive view is handed while the model writes the call.
 */
export function readPartialArguments(text: string): Record<string, unknown> {
  const start = skipSpace(text, 0);
  if (text[start] !== "{") return {};
  return readObject(text, start).value as Record<string, unknown>;
}
