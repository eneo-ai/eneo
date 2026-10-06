import { cn } from "@/lib/utils";

/**
 * Bordered container for the tables on space pages (knowledge, files, skills,
 * the overview) with a sunken header row. The Astryx Table inside scrolls
 * sideways in its own keyboard-reachable region on narrow screens.
 */
export function SpaceTableFrame({
  children,
  className
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "border-ax-border bg-ax-card rounded-ax-container [&_thead_tr]:bg-ax-sunken overflow-hidden border",
        className
      )}
    >
      {children}
    </div>
  );
}
