"use client";

import { OverviewAssistants } from "@/features/spaces/overview/overview-assistants";
import { OverviewKnowledge } from "@/features/spaces/overview/overview-knowledge";
import { OverviewManage } from "@/features/spaces/overview/overview-manage";
import { useSpace } from "@/features/spaces/use-space";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";

/**
 * The space overview: things to act on instead of count tiles. The newest
 * assistants and knowledge in one flowing column. The space's facts live
 * where they are managed: the classification in the space header, the models
 * on the settings tab, the members on theirs. A phone, which has tabs only
 * for the content, lists those under "Hantera ytan" (decision 24).
 */
export function SpaceOverview() {
  const { space, can } = useSpace();
  const showAssistants = !space.organization && can("read", "assistant");
  const showKnowledge = can("read", "collection") || can("read", "website");
  const phone = useMediaMatch(PHONE_QUERY);

  return (
    <div className="flex w-full min-w-0 flex-col gap-7">
      {showAssistants ? <OverviewAssistants /> : null}
      {showKnowledge ? <OverviewKnowledge /> : null}
      {phone !== false ? (
        <div className="md:hidden">
          <OverviewManage />
        </div>
      ) : null}
    </div>
  );
}
