import { Skeleton } from "@astryxdesign/core/Skeleton";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";

export type LoadingStateProps = {
  /** Screen-reader announcement; defaults to "Laddar…". */
  label?: string;
  /** Number of placeholder rows. */
  rows?: number;
  /** `rows`: list/table-height bars (default) · `text`: paragraph lines. */
  variant?: "rows" | "text";
  className?: string;
};

const TEXT_WIDTHS = ["100%", "92%", "96%", "70%"];

/**
 * Skeleton placeholder for content that is loading: a polite, busy status
 * region with Astryx Skeleton bars shaped like the content. Use it instead of
 * an EmptyState that says "Loading".
 *
 * @example
 * {isPending ? <LoadingState rows={5} /> : <UserTable users={users} />}
 */
export function LoadingState({ label, rows = 3, variant = "rows", className }: LoadingStateProps) {
  const t = useTranslations();
  const isText = variant === "text";

  return (
    <div
      role="status"
      aria-live="polite"
      aria-busy="true"
      className={cn("flex flex-col", isText ? "gap-2" : "gap-3", className)}
    >
      <span className="sr-only">{label ?? t("loading")}</span>
      {Array.from({ length: Math.max(1, rows) }, (_, index) => (
        <Skeleton
          key={index}
          index={index}
          height={isText ? 14 : 40}
          width={isText ? TEXT_WIDTHS[index % TEXT_WIDTHS.length] : "100%"}
          radius={isText ? 1 : 2}
        />
      ))}
    </div>
  );
}
