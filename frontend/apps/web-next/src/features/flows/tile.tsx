import { useTranslations } from "use-intl";
import { useClientTimeText } from "@/components/composites/client-time";
import { EntityAvatar } from "@/components/composites/entity-avatar";
import { ResourceCard } from "@/components/composites/resource-tile";
import { useSpace } from "@/features/spaces/use-space";
import { FlowActions } from "./actions";
import type { FlowSparse } from "./flows-api";
import { flowKindLine } from "./flow-labels";

/**
 * Card for a flow; the card opens the flow, where it is run. The tokens say
 * what it takes in and gives back, how many steps it has, whose it is
 * (`owner`, from `flowOwner`) and when it last changed. It shows no state:
 * those who manage flows see them grouped by it, and others see published
 * flows only.
 */
export function FlowTile({
  flow,
  owner
}: {
  flow: FlowSparse;
  /** Whose the flow is, in words; null when it does not say. */
  owner: string | null;
}) {
  const t = useTranslations();
  const { routeId } = useSpace();
  const kind = flowKindLine(flow, t);
  // A flow never changed since it was created says when that was.
  const changed = useClientTimeText(flow.updated_at ?? flow.created_at, "date");

  return (
    <ResourceCard
      href={`/spaces/${routeId}/flows/${flow.id}`}
      name={flow.name}
      tile={<EntityAvatar name={flow.name} id={flow.id} size="lg" className="size-9" />}
      description={flow.description}
      meta={[
        ...(kind ? [kind] : []),
        t("flows_step_count", { count: flow.step_count }),
        ...(owner ? [t("flows_row_owner", { name: owner })] : []),
        ...(changed ? [t("flows_row_updated", { date: changed })] : [])
      ]}
      actions={<FlowActions flow={flow} />}
    />
  );
}
