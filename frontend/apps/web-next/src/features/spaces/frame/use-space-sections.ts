import { useQuery } from "@tanstack/react-query";
import { useAppContext } from "@/components/providers/app-context";
import { flowsListQueryOptions } from "@/features/flows/flows-api";
import { browserApi } from "@/lib/api/browser";
import { useSpace } from "../use-space";
import { spaceSections, type SpaceSection } from "./space-sections";

/**
 * The space's tabs for this user, flows included when the tenant has them. The
 * other counts come with the space; the flows are listed separately (the same
 * list the flows tab shows), so their count arrives once that list is read.
 */
export function useSpaceSections(): SpaceSection[] {
  const { space, routeId, can } = useSpace();
  const { featureFlags } = useAppContext();
  const showsFlows = featureFlags.flows && !space.organization && can("read", "app");
  const flows = useQuery({
    ...flowsListQueryOptions(browserApi, space.id),
    enabled: showsFlows
  });
  return spaceSections(space, can, routeId, {
    flows: featureFlags.flows,
    flowCount: flows.data?.length
  });
}
