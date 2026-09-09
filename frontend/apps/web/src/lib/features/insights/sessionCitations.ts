/*
    Copyright (c) 2026 Sundsvalls Kommun

    Licensed under the MIT License.
*/

/**
 * The insights prompt asks the model to cite conversations as
 * `(session <uuid>)`. Rewriting those into markdown links lets the chat
 * open the cited conversation in the existing preview instead of showing a
 * bare id.
 */

const UUID = "[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}";

/** `(session <uuid>)` and `(session_id <uuid>)`, optionally in backticks. */
const CITATION = new RegExp(`\\(\\s*\`?session(?:_id)?[\\s=:]*\`?(${UUID})\`?\\s*\\)`, "g");

/** Hash prefix of the links the rewrite produces; the click handler keys on it. */
export const SESSION_LINK_PREFIX = "#insight-session-";

/** Short, recognisable form of a session id for link text. */
export function shortSessionId(sessionId: string): string {
  return sessionId.slice(0, 8);
}

/**
 * Replace every `(session <uuid>)` citation with a markdown link whose href
 * is `#insight-session-<uuid>`. Other text is left untouched.
 */
export function linkSessionCitations(markdown: string, label: string): string {
  return markdown.replace(
    CITATION,
    (_match, sessionId: string) =>
      `([${label} ${shortSessionId(sessionId)}](${SESSION_LINK_PREFIX}${sessionId.toLowerCase()}))`
  );
}

/** The cited session id when `href` is one of the rewrite's links, else null. */
export function citedSessionId(href: string | null | undefined): string | null {
  if (!href) return null;
  const index = href.indexOf(SESSION_LINK_PREFIX);
  if (index === -1) return null;
  const id = href.slice(index + SESSION_LINK_PREFIX.length);
  return new RegExp(`^${UUID}$`).test(id) ? id : null;
}
