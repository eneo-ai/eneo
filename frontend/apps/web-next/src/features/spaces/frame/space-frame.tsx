"use client";

import { useSpaceSegments } from "@/lib/navigation";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
import { SpaceHeader } from "./space-header";
import { SpacePhoneHeader } from "./space-phone-header";
import { spaceRoute } from "./space-sections";

/**
 * Chrome around every route of one space. The chat renders full-bleed (it has
 * its own header and pins its composer to the bottom), and so does an editor
 * (assistant, app, group chat): its sticky header carries the breadcrumb back
 * to the space and the tab, the save state and the actions, so stacking the
 * space header and tabs on top would only push its own section tabs off the
 * screen. Every other page gets the space header and tabs above it and
 * scrolls with them in the app shell's page panel, `main#main-content`, the
 * one scroll container: the header scrolls away (nothing sticky covers
 * focus), Page Down works right after the skip link, and the page reflows at
 * 320 px / 400 %.
 *
 * Pages sit in a `p-6` inset (16 px on a phone). A page that spans the frame
 * edge to edge, such as the editors with their sticky header, marks its root
 * element with `data-space-full-bleed` and the inset goes away.
 *
 * A phone gets SpacePhoneHeader instead of the header (decision 24). CSS
 * picks one from the server render on; once the width is known, the other
 * is dropped.
 */
export function SpaceFrame({ children }: { children: React.ReactNode }) {
  const segments = useSpaceSegments();
  const route = spaceRoute(segments);
  const phone = useMediaMatch(PHONE_QUERY);

  if (route.kind === "chat") {
    return <div className="flex min-h-0 min-w-0 flex-1 flex-col">{children}</div>;
  }

  if (route.kind === "editor") {
    return <div className="flex min-w-0 flex-1 flex-col">{children}</div>;
  }

  if (route.kind === "workspace") {
    return <div className="flex min-w-0 flex-1 flex-col lg:min-h-0">{children}</div>;
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      {phone !== false ? <SpacePhoneHeader route={route} segments={segments} /> : null}
      {phone !== true ? <SpaceHeader route={route} className="max-md:hidden" /> : null}
      <div className="flex min-w-0 flex-1 flex-col p-4 has-[[data-space-full-bleed]]:p-0 md:p-6">
        {children}
      </div>
    </div>
  );
}
