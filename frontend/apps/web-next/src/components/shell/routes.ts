/**
 * Route knowledge the shell needs, kept pure so it can be unit tested: which
 * routes usually render their own mobile header, which navigation item a URL
 * selects, and the links the shell builds.
 */

import type { RecentConversation } from "@/lib/api/conversations";
import { spaceRouteId } from "@/features/spaces/space";

/**
 * Window event a page's own phone header (the chat's) dispatches from its
 * menu button; the shell answers by opening the navigation drawer. The one
 * definition: import it, don't repeat the string.
 *
 * @example window.dispatchEvent(new CustomEvent(OPEN_NAV_EVENT))
 */
export const OPEN_NAV_EVENT = "eneo:open-nav";

/** Where "Ny konversation" goes: a fresh conversation with the personal assistant. */
export const NEW_CONVERSATION_HREF = "/spaces/personal/chat";

/** What a saved conversation's link needs: its partner and that partner's space. */
type ConversationLink = Pick<RecentConversation, "id"> & {
  partner: Pick<RecentConversation["partner"], "type" | "id">;
  space: Pick<RecentConversation["space"], "id" | "personal" | "organization">;
};

/**
 * Where a saved conversation opens: its space's chat with its partner, in the
 * URL scheme the space chat builds itself. The space's own assistant (in the
 * personal space: the personal chat) needs no `type` and `id`.
 */
export function conversationHref({ id, partner, space }: ConversationLink): string {
  const params = new URLSearchParams();
  if (partner.type !== "default-assistant") {
    params.set("type", partner.type);
    params.set("id", partner.id);
  }
  params.set("session_id", id);
  return `/spaces/${spaceRouteId(space)}/chat?${params}`;
}

function segmentsOf(pathname: string): string[] {
  return pathname.split("/").filter(Boolean);
}

/**
 * Chat routes render their own compact mobile header (menu, assistant, new
 * conversation): `/spaces/[spaceId]/chat…` and `/dashboard/[assistantId]…`
 * (not the `/dashboard` catalog or `/dashboard/app/…`). The shell only uses
 * this before hydration, to leave its top bar out of the server render there;
 * afterwards the mounted header decides (`useOwnMobileHeader`).
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

/** A main-navigation destination other than one conversation. */
type PlaceTarget =
  | { kind: "new-conversation" }
  | { kind: "assistants" }
  | { kind: "space"; routeId: string }
  | { kind: "all-spaces" }
  | { kind: "organization" }
  | { kind: "none" };

/**
 * The main-navigation destination a URL belongs to, for `aria-current`. A
 * saved conversation is current under "Senaste" when listed there;
 * `otherwise` is current when it isn't (see `currentNavTarget`).
 */
export type NavTarget =
  PlaceTarget | { kind: "conversation"; sessionId: string; otherwise: PlaceTarget };

type SearchParamsLike = Pick<URLSearchParams, "get">;

export function navTarget(pathname: string, searchParams: SearchParamsLike | null): NavTarget {
  const segments = segmentsOf(pathname);
  const [first, second, third] = segments;

  if (first === "dashboard") return { kind: "assistants" };
  if (first !== "spaces" || !second) return { kind: "none" };
  if (second === "list") return { kind: "all-spaces" };

  const space: PlaceTarget =
    second === "organization" ? { kind: "organization" } : { kind: "space", routeId: second };
  if (third !== "chat" || segments.length !== 3) return space;

  // The personal chat with its default assistant belongs to "Ny konversation"
  // and "Senaste"; other partners in the personal space to "Personligt".
  const isPersonalChat =
    second === "personal" && !searchParams?.get("type") && !searchParams?.get("id");
  const sessionId = searchParams?.get("session_id");
  if (sessionId) {
    return {
      kind: "conversation",
      sessionId,
      otherwise: isPersonalChat ? { kind: "none" } : space
    };
  }
  return isPersonalChat ? { kind: "new-conversation" } : space;
}

/** One current destination: the conversation when "Senaste" lists it, else its place. */
export function currentNavTarget(
  target: NavTarget,
  listedSessionIds: readonly string[]
): NavTarget {
  if (target.kind !== "conversation" || listedSessionIds.includes(target.sessionId)) return target;
  return target.otherwise;
}
