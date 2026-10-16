import { useQuery } from "@tanstack/react-query";
import {
  spaceHasPermission,
  type ResourcePermission,
  type Space,
  type SpaceResource
} from "../space";

/**
 * Test-only stand-in for `useSpace`: like the real hook, the space lives in
 * the ["spaces", routeId] query, so the invalidation after a delete or move
 * refetches it from `current()` and the item's row goes away.
 *
 * @example
 * vi.mock("@/features/spaces/use-space", async () => {
 *   const { useSpaceFromQuery } = await import("@/features/spaces/testing/space-query");
 *   return { useSpace: () => useSpaceFromQuery(() => state.space as Space) };
 * });
 */
export function useSpaceFromQuery(current: () => Space, routeId = "space-1") {
  const { data: space } = useQuery({
    queryKey: ["spaces", routeId],
    queryFn: current,
    initialData: current
  });
  return {
    space,
    routeId,
    can: (action: ResourcePermission, resource: SpaceResource) =>
      spaceHasPermission(space, action, resource)
  };
}
