/**
 * Route knowledge the shell needs, kept pure so it can be unit tested: which
 * routes render their own mobile header, which navigation item a URL selects,
 * and the links the shell builds.
 */

/**
 * Window event the chat's compact mobile header dispatches from its menu
 * button; the shell answers by opening the navigation drawer.
 *
 * @example window.dispatchEvent(new CustomEvent(OPEN_NAV_EVENT))
 */
export const OPEN_NAV_EVENT = "eneo:open-nav";

/** Where "Ny konversation" goes: a fresh conversation with the personal assistant. */
export const NEW_CONVERSATION_HREF = "/spaces/personal/chat";

/** A personal-assistant conversation, in the URL scheme the personal chat uses. */
export function conversationHref(sessionId: string): string {
  return `${NEW_CONVERSATION_HREF}?${new URLSearchParams({ session_id: sessionId })}`;
}

function segmentsOf(pathname: string): string[] {
  return pathname.split("/").filter(Boolean);
}

/**
 * Chat routes render their own compact mobile header (menu, assistant, new
 * conversation), so the shell must not add its mobile top bar there:
 * `/spaces/[spaceId]/chat…` and `/dashboard/[assistantId]…` (not the
 * `/dashboard` catalog or `/dashboard/app/…`).
 */
export function isChatRoute(pathname: string): boolean {
  const [first, second, third] = segmentsOf(pathname);
  if (first === "spaces") return second !== undefined && third === "chat";
  if (first === "dashboard") return second !== undefined && second !== "app";
  return false;
}

/** Which navigation the SideNav shows. */
export type NavVariant = "main" | "admin";

/** `/admin` and everything below it: the SideNav switches to admin mode. */
export function isAdminRoute(pathname: string): boolean {
  return segmentsOf(pathname)[0] === "admin";
}

/** The space route id (`personal`, `organization` or a space id) of a space page. */
export function spaceRouteIdFromPath(pathname: string): string | null {
  const [first, second] = segmentsOf(pathname);
  if (first !== "spaces" || !second || second === "list") return null;
  return second;
}

/** The main-navigation destination a URL belongs to, for `aria-current`. */
export type NavTarget =
  | { kind: "new-conversation" }
  | { kind: "conversation"; sessionId: string }
  | { kind: "assistants" }
  | { kind: "space"; routeId: string }
  | { kind: "all-spaces" }
  | { kind: "organization" }
  | { kind: "none" };

type SearchParamsLike = Pick<URLSearchParams, "get">;

export function navTarget(pathname: string, searchParams: SearchParamsLike | null): NavTarget {
  const segments = segmentsOf(pathname);
  const [first, second, third] = segments;

  if (first === "dashboard") return { kind: "assistants" };
  if (first !== "spaces" || !second) return { kind: "none" };
  if (second === "list") return { kind: "all-spaces" };
  if (second === "organization") return { kind: "organization" };

  // The personal chat with its default assistant: a new conversation or a
  // saved one. Other partners in the personal space belong to "Personligt".
  const isDefaultAssistantChat =
    second === "personal" &&
    third === "chat" &&
    segments.length === 3 &&
    !searchParams?.get("type") &&
    !searchParams?.get("id");
  if (isDefaultAssistantChat) {
    const sessionId = searchParams?.get("session_id");
    return sessionId ? { kind: "conversation", sessionId } : { kind: "new-conversation" };
  }

  return { kind: "space", routeId: second };
}
