"use client";

import { useSpace } from "@/features/spaces/use-space";
import { OverviewAside } from "@/features/spaces/overview/overview-aside";
import { OverviewAssistants } from "@/features/spaces/overview/overview-assistants";
import { OverviewKnowledge } from "@/features/spaces/overview/overview-knowledge";

/**
 * The space overview: things to act on instead of count tiles. The newest
 * assistants and the knowledge sources (with sync problems surfaced), and
 * beside them what the space is set up with and who is in it. The space
 * header above carries the name, description and primary actions.
 */
export function SpaceOverview() {
  const { space, can } = useSpace();
  const showAssistants = !space.organization && can("read", "assistant");
  const showKnowledge = can("read", "collection") || can("read", "website");

  return (
    <div className="grid w-full items-start gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
      <div className="flex min-w-0 flex-col gap-7">
        {showAssistants ? <OverviewAssistants /> : null}
        {showKnowledge ? <OverviewKnowledge /> : null}
      </div>
      <OverviewAside />
    </div>
  );
}
