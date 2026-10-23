"use client";

import { useSuspenseQuery } from "@tanstack/react-query";
import { createContext, useContext, useMemo } from "react";
import { browserApi } from "@/lib/api/browser";
import {
  spaceHasPermission,
  spaceQueryOptions,
  type ResourcePermission,
  type Space,
  type SpaceResource,
  type SpaceRouteId
} from "./space";

const SpaceRouteContext = createContext<SpaceRouteId | null>(null);

export function SpaceProvider({
  routeId,
  children
}: {
  routeId: SpaceRouteId;
  children: React.ReactNode;
}) {
  return <SpaceRouteContext.Provider value={routeId}>{children}</SpaceRouteContext.Provider>;
}

export function useSpaceRouteId(): SpaceRouteId {
  const routeId = useContext(SpaceRouteContext);
  if (!routeId) throw new Error("useSpace must be used inside a space layout");
  return routeId;
}

/**
 * The current space (hydrated from the layout's server prefetch) plus a
 * bound permission helper.
 */
export function useSpace(): {
  space: Space;
  routeId: SpaceRouteId;
  can: (action: ResourcePermission, resource: SpaceResource) => boolean;
} {
  const routeId = useSpaceRouteId();
  const { data: space } = useSuspenseQuery(spaceQueryOptions(browserApi, routeId));
  return useMemo(
    () => ({
      space,
      routeId,
      can: (action, resource) => spaceHasPermission(space, action, resource)
    }),
    [space, routeId]
  );
}
