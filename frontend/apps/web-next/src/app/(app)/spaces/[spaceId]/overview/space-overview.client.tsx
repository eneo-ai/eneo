"use client";

import { useSpace } from "@/features/spaces/use-space";
import { OverviewAssistants } from "@/features/spaces/overview/overview-assistants";
import { OverviewKnowledge } from "@/features/spaces/overview/overview-knowledge";

/**
 * The space overview: things to act on instead of count tiles. The newest
 * assistants and knowledge in one flowing column. The space's facts live
 * where they are managed: the classification in the space header, the models
 * on the settings tab, the members on theirs.
 */
export function SpaceOverview() {
  const { space, can } = useSpace();
  const showAssistants = !space.organization && can("read", "assistant");
  const showKnowledge = can("read", "collection") || can("read", "website");

  return (
    <div className="flex w-full min-w-0 flex-col gap-7">
      {showAssistants ? <OverviewAssistants /> : null}
      {showKnowledge ? <OverviewKnowledge /> : null}
    </div>
  );
}
