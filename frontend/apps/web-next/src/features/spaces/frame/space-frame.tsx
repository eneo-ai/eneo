"use client";

import { useSelectedLayoutSegments } from "next/navigation";
import { SpaceHeader } from "./space-header";
import { spaceRoute } from "./space-sections";

/**
 * Chrome around every route of one space. The chat renders full-bleed (it has
 * its own header and pins its composer to the bottom). Every other page gets
 * the space header and tabs above it and scrolls with them in the app shell's
 * page panel, `main#main-content`, the one scroll container: the header
 * scrolls away (nothing sticky covers focus), Page Down works right after the
 * skip link, and the page reflows at 320 px / 400 %.
 *
 * Pages sit in a `p-6` inset. A page that spans the frame edge to edge, such
 * as the assistant editor with its sticky header, marks its root element with
 * `data-space-full-bleed` and the inset goes away.
 */
export function SpaceFrame({ children }: { children: React.ReactNode }) {
  const route = spaceRoute(useSelectedLayoutSegments());

  if (route.kind === "chat") {
    return <div className="flex min-h-0 min-w-0 flex-1 flex-col">{children}</div>;
  }

  return (
    <div className="flex min-w-0 flex-1 flex-col">
      <SpaceHeader route={route} />
      <div className="flex min-w-0 flex-1 flex-col p-6 has-[[data-space-full-bleed]]:p-0">
        {children}
      </div>
    </div>
  );
}
