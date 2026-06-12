import { queryOptions } from "@tanstack/react-query";
import type { EneoClient } from "@/lib/api/browser";
import { unwrap } from "@/lib/api/errors";
import type { Schema } from "@/lib/api/models";

export type Space = Schema<"SpacePublic">;
export type SpaceSparse = Schema<"SpaceSparse">;
export type SpaceMember = Schema<"SpaceMember">;
export type SpaceRoleValue = Schema<"SpaceRoleValue">;
export type ResourcePermission = Schema<"ResourcePermission">;

/** Route segment for a space: personal and organization spaces use aliases. */
export type SpaceRouteId = "personal" | "organization" | (string & {});

export type SpaceResource =
  | "space"
  | "assistant"
  | "default_assistant"
  | "group_chat"
  | "service"
  | "website"
  | "integrationKnowledge"
  | "collection"
  | "member"
  | "group_member"
  | "app";

/**
 * Space-level permission check, ported from the Svelte SpacesManager: each
 * resource list carries its own `permissions` array.
 */
export function spaceHasPermission(
  space: Space,
  action: ResourcePermission,
  resource: SpaceResource
): boolean {
  switch (resource) {
    case "space":
      return space.permissions?.includes(action) ?? false;
    case "assistant":
      return space.applications?.assistants.permissions?.includes(action) ?? false;
    case "group_chat":
      return space.applications?.group_chats.permissions?.includes(action) ?? false;
    case "default_assistant":
      return space.default_assistant?.permissions?.includes(action) ?? false;
    case "app":
      return space.applications?.apps.permissions?.includes(action) ?? false;
    case "service":
      return space.applications?.services.permissions?.includes(action) ?? false;
    case "collection":
      return space.knowledge.groups.permissions?.includes(action) ?? false;
    case "website":
      return space.knowledge.websites.permissions?.includes(action) ?? false;
    case "integrationKnowledge":
      return space.knowledge.integration_knowledge_list.permissions?.includes(action) ?? false;
    case "member":
      return space.members.permissions?.includes(action) ?? false;
    case "group_member":
      return space.group_members?.permissions?.includes(action) ?? false;
    default:
      return false;
  }
}

export function spaceRouteId(space: Pick<Space, "id" | "personal" | "organization">): SpaceRouteId {
  if (space.personal) return "personal";
  if (space.organization) return "organization";
  return space.id;
}

/** Fetch one space by route id (resolves the personal/organization aliases). */
export function spaceQueryOptions(api: EneoClient, routeId: SpaceRouteId) {
  return queryOptions({
    queryKey: ["spaces", routeId],
    queryFn: (): Promise<Space> => {
      if (routeId === "personal") return unwrap(api.GET("/api/v1/spaces/type/personal/"));
      if (routeId === "organization") return unwrap(api.GET("/api/v1/spaces/type/organization/"));
      return unwrap(api.GET("/api/v1/spaces/{id}/", { params: { path: { id: routeId } } }));
    }
  });
}

export function spacesListQueryOptions(api: EneoClient) {
  return queryOptions({
    queryKey: ["spaces"],
    queryFn: async (): Promise<SpaceSparse[]> => {
      const page = await unwrap(api.GET("/api/v1/spaces/"));
      return page.items;
    }
  });
}
