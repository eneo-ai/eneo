import { cn } from "@/lib/utils";

/**
 * Bordered container for the tables on space and admin pages (knowledge,
 * files, skills, users) with a sunken header row. The Astryx Table inside scrolls
 * sideways in its own keyboard-reachable region on narrow screens; a pinned
 * column (Table `pinnedColumn`) takes the colours of the rows it covers.
 *
 * On a phone the table runs edge to edge (decision 9): over the page's 16 px
 * gutters, on the page's own surface, with a rule above and below. Astryx's
 * container inset keeps its first and last cells on the 16 px content line.
 */
export function TableFrame({
  children,
  className
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "border-ax-border bg-ax-card rounded-ax-container [&_thead_tr]:bg-ax-sunken overflow-hidden border [--table-sticky-background:var(--color-ax-card)] [&_thead_tr]:[--table-sticky-background:var(--color-ax-sunken)]",
        "max-md:-mx-4 max-md:rounded-none max-md:border-x-0 max-md:bg-transparent max-md:px-4 max-md:[--container-padding-inline-end:1rem] max-md:[--container-padding-inline-start:1rem] max-md:[--table-sticky-background:var(--color-ax-surface)] max-md:[&_thead_tr]:bg-transparent max-md:[&_thead_tr]:[--table-sticky-background:var(--color-ax-surface)]",
        className
      )}
    >
      {children}
    </div>
  );
}
