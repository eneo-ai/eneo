"use client";

import { useSelectedLayoutSegments } from "next/navigation";
import { SpaceHeader } from "./space-header";
import { spaceRoute } from "./space-sections";

/**
 * Chrome around every route of one space. The chat renders full-bleed (it has
 * its own header and pins its composer to the bottom). Everything else scrolls
 * in one container: the space header and tabs scroll away with the content, so
 * nothing sticky ever covers focus and the page reflows at 320 px / 400 %.
 *
 * The container keeps the `p-6` inset the space pages were built against: the
 * assistant editor cancels it with `-m-6` and pins its own header with
 * `sticky -top-6`.
 */
export function SpaceFrame({ children }: { children: React.ReactNode }) {
  const route = spaceRoute(useSelectedLayoutSegments());

  if (route.kind === "chat") {
    return <div className="flex min-h-0 min-w-0 flex-1 flex-col">{children}</div>;
  }

  return (
    <div className="flex min-h-0 min-w-0 flex-1 flex-col overflow-y-auto p-6">
      <SpaceHeader route={route} className="-mx-6 -mt-6" />
      <div className="flex min-w-0 flex-1 flex-col pt-6">{children}</div>
    </div>
  );
}
