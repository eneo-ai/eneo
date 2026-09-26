import { EmptyState as AstryxEmptyState } from "@astryxdesign/core/EmptyState";
import { cn } from "@/lib/utils";

export type EmptyStateProps = {
  /** What is empty, specifically ("No collections yet", not "No data"). */
  title: string;
  /** Why it is empty or what to do next. */
  description?: string;
  /** Decorative icon above the title, e.g. `<Inbox />` from lucide-react. */
  icon?: React.ReactNode;
  /** One or two next-step buttons. */
  actions?: React.ReactNode;
  /** Legacy actions slot — same as `actions`, which wins when both are set. */
  children?: React.ReactNode;
  /**
   * Heading tag for the title (document outline only; the size is fixed). 1
   * when the state is the whole page, such as a route that failed to load.
   */
  headingLevel?: 1 | 2 | 3 | 4;
  /** Tighter spacing for cards, side panels and table bodies. */
  isCompact?: boolean;
  /** Dashed placeholder frame (default). Turn off inside an already framed surface. */
  framed?: boolean;
  className?: string;
};

/**
 * Placeholder for an empty list, zero search results or a first-time setup,
 * built on Astryx EmptyState (announced politely via role="status"). Not a
 * loading indicator — use LoadingState while data is pending.
 *
 * @example
 * <EmptyState
 *   icon={<Library />}
 *   title={t("there_are_currently_no_collections_configured")}
 *   actions={<CreateCollectionButton />}
 * />
 */
export function EmptyState({
  title,
  description,
  icon,
  actions,
  children,
  headingLevel = 2,
  isCompact = false,
  framed = true,
  className
}: EmptyStateProps) {
  const actionSlot = actions ?? children;
  // `can(...) && <Button />` passes `false`; Astryx would still render (and
  // space) an empty actions row for anything non-nullish.
  const hasActions = actionSlot != null && typeof actionSlot !== "boolean" && actionSlot !== "";

  return (
    <AstryxEmptyState
      title={title}
      description={description}
      icon={
        icon ? (
          <span className="bg-ax-muted text-ax-text-secondary rounded-ax-container flex size-10 items-center justify-center [&_svg]:size-5">
            {icon}
          </span>
        ) : undefined
      }
      actions={hasActions ? actionSlot : undefined}
      headingLevel={headingLevel}
      isCompact={isCompact}
      className={cn(
        framed && "border-ax-border-strong rounded-ax-container border border-dashed",
        className
      )}
    />
  );
}
