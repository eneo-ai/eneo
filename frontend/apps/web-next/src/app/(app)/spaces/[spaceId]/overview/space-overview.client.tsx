"use client";

import { useSpace } from "@/features/spaces/use-space";
import { OverviewAside } from "@/features/spaces/overview/overview-aside";
import { OverviewAssistants } from "@/features/spaces/overview/overview-assistants";
import { OverviewKnowledge } from "@/features/spaces/overview/overview-knowledge";

/**
 * The space overview: things to act on instead of count tiles. The newest
 * assistants and space facts share the top row; knowledge sources get the
 * full width below so names, sync status and actions stay readable.
 */
export function SpaceOverview() {
  const { space, can } = useSpace();
  const showAssistants = !space.organization && can("read", "assistant");
  const showKnowledge = can("read", "collection") || can("read", "website");

  return (
    <div className="grid w-full items-start gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]">
      {showAssistants ? <OverviewAssistants /> : null}
      <div className={showAssistants ? "min-w-0" : "min-w-0 xl:col-span-2 xl:max-w-md"}>
        <OverviewAside />
      </div>
      {showKnowledge ? (
        <div className="min-w-0 xl:col-span-2">
          <OverviewKnowledge />
        </div>
      ) : null}
    </div>
  );
}
