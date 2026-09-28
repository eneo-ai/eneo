"use client";

import { useSpace } from "@/features/spaces/use-space";
import { OverviewAside } from "@/features/spaces/overview/overview-aside";
import { OverviewAssistants } from "@/features/spaces/overview/overview-assistants";
import { OverviewKnowledge } from "@/features/spaces/overview/overview-knowledge";

/**
 * The space overview: things to act on instead of count tiles. The newest
 * assistants and knowledge stay in one flowing column, beside the space facts.
 * The compact knowledge list stays readable in that column without a wide table.
 */
export function SpaceOverview() {
  const { space, can } = useSpace();
  const showAssistants = !space.organization && can("read", "assistant");
  const showKnowledge = can("read", "collection") || can("read", "website");
  const showMain = showAssistants || showKnowledge;

  return (
    <div
      className={
        showMain
          ? "grid w-full items-start gap-6 xl:grid-cols-[minmax(0,1fr)_20rem]"
          : "w-full max-w-md"
      }
    >
      {showMain ? (
        <div className="flex min-w-0 flex-col gap-7">
          {showAssistants ? <OverviewAssistants /> : null}
          {showKnowledge ? <OverviewKnowledge /> : null}
        </div>
      ) : null}
      <OverviewAside />
    </div>
  );
}
