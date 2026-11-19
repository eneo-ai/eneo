/**
 * Mentions in a chat message: a name the person reads and a key a page
 * resolves, written `@[<name>](<scheme>:<key>)`. The scheme says what the
 * key names (`step:` a flow's step, `setting:` an assistant's setting), so
 * one message can hold mentions of several kinds. Pure and unit-tested.
 */

/** Every mention of the scheme in a text; group 1 is the name, group 2 the key. */
export function mentionPattern(scheme: string): RegExp {
  return new RegExp(String.raw`@\[([^\]\n]+)\]\(${scheme}:([^)\s]+)\)`, "g");
}

/** A mention as written in a message. Brackets leave the name; an empty name is "?". */
export function mentionText(name: string, scheme: string, key: string): string {
  const shown = name.trim().replace(/[[\]]/g, "") || "?";
  return `@[${shown}](${scheme}:${key})`;
}

export type MentionPart =
  { kind: "text"; text: string } | { kind: "mention"; raw: string; name: string; key: string };

/** The text split into plain text and the scheme's mentions, in order. */
export function mentionParts(text: string, scheme: string): MentionPart[] {
  const parts: MentionPart[] = [];
  let cursor = 0;
  for (const match of text.matchAll(mentionPattern(scheme))) {
    const start = match.index ?? 0;
    if (start > cursor) parts.push({ kind: "text", text: text.slice(cursor, start) });
    parts.push({ kind: "mention", raw: match[0], name: match[1]!, key: match[2]! });
    cursor = start + match[0].length;
  }
  if (cursor < text.length) parts.push({ kind: "text", text: text.slice(cursor) });
  return parts;
}

/** The mention a text is, as written, or null for anything else. */
export function parseMention(raw: string, scheme: string): { name: string; key: string } | null {
  const parts = mentionParts(raw, scheme);
  const part = parts[0];
  return parts.length === 1 && part?.kind === "mention" ? { name: part.name, key: part.key } : null;
}

/**
 * Whether a link's address goes somewhere: an address with a host
 * (`https://…`), a mail or phone address, a path, a query or an anchor.
 */
function isLinkAddress(address: string): boolean {
  return /^(?:[a-z][a-z0-9+.-]*:\/\/|mailto:|tel:|[/?#]|\.\.?\/)/i.test(address);
}

/**
 * A mention as a model sometimes writes it, without the scheme:
 * `@[Namn](name)`, a name and an address no link can go to. The whole
 * address is the key, so read the scheme's form (`parseMention`) first; what
 * the key names, if anything, is for the page to say. Null for anything
 * else, a mention of a web address (`@[text](https://…)`) included.
 */
export function parseBareMention(raw: string): { name: string; key: string } | null {
  const match = /^@\[([^\]\n]+)\]\(([^)\s]+)\)$/.exec(raw);
  return match && !isLinkAddress(match[2]!) ? { name: match[1]!, key: match[2]! } : null;
}
