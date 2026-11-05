import { cn } from "@/lib/utils";

/**
 * The pages' shared column: one readable width (1152 px) centred in the page
 * panel, so every list and overview page starts on the same left edge and
 * the heading stays put from page to page. On a laptop the panel is narrower
 * than the column and the column fills it.
 */
export const PAGE_COLUMN = "mx-auto w-full max-w-6xl";

/**
 * The page inset with the shared column inside it. A page renders in it and
 * centres nothing of its own; a form or reading page may cap itself narrower
 * (`max-w-4xl`), starting on the same edge.
 */
export function PageFrame({
  className,
  children
}: {
  className?: string;
  children: React.ReactNode;
}) {
  return (
    <div className="wide:p-6 flex min-w-0 flex-1 flex-col p-4">
      <div className={cn(PAGE_COLUMN, "flex min-w-0 flex-1 flex-col", className)}>{children}</div>
    </div>
  );
}
