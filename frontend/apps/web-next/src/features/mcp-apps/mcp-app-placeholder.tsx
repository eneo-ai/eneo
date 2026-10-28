import { Skeleton } from "@astryxdesign/core/Skeleton";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** The room a view is given while it has not said how much it needs. */
export const UNSIZED_VIEW_HEIGHT = 320;

/**
 * The height a view takes before it reports its size: an earlier answer's
 * view holds its place, one shown with the answer being written starts with
 * none, so a view with nothing to show never flickers into the answer.
 */
export function unsizedHeight(live: boolean): number {
  return live ? 0 : UNSIZED_VIEW_HEIGHT;
}

/** Where a view will be, until it can show itself: its frame's code or its link is still loading. */
export function McpAppViewSkeleton({ height, inline }: { height: number; inline: boolean }) {
  return (
    <div
      aria-hidden="true"
      className={cn(
        "rounded-ax-container mt-2 overflow-hidden",
        inline && height === 0 && "hidden"
      )}
      style={inline ? { height } : undefined}
    >
      <Skeleton radius={3} />
    </div>
  );
}

/** A line in place of a view that cannot be shown. */
export function McpAppViewNote({ children }: { children: ReactNode }) {
  return (
    <p
      role="note"
      className="border-ax-border-strong text-ax-text-secondary rounded-ax-container mt-2 border border-dashed px-3 py-2 text-xs"
    >
      {children}
    </p>
  );
}
