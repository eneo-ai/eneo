import { Heading } from "@astryxdesign/core/Heading";
import { Text } from "@astryxdesign/core/Text";
import { cn } from "@/lib/utils";

export type SpaceSectionHeaderProps = {
  /** The tab page's title; an h2 under the space name (the page's h1). */
  title: string;
  description?: string;
  /** Page-level actions, right-aligned; they wrap below the title on narrow screens. */
  actions?: React.ReactNode;
  /** `data-tour` anchor for the guided tour. */
  tour?: string;
  className?: string;
};

/**
 * Title block for a page inside the space frame (a tab such as Kunskap or
 * Medlemmar). The space header above already renders the h1 and breadcrumbs,
 * so this is PageHeader's layout one level down the outline.
 */
export function SpaceSectionHeader({
  title,
  description,
  actions,
  tour,
  className
}: SpaceSectionHeaderProps) {
  const hasActions = actions != null && typeof actions !== "boolean";

  return (
    <div
      data-tour={tour}
      className={cn("flex flex-wrap items-center justify-between gap-x-4 gap-y-3", className)}
    >
      <div className="flex min-w-0 flex-col gap-1">
        <Heading level={2} className="break-words">
          {title}
        </Heading>
        {description ? (
          <Text as="p" type="body" color="secondary" className="max-w-prose">
            {description}
          </Text>
        ) : null}
      </div>
      {hasActions ? <div className="flex flex-wrap items-center gap-2">{actions}</div> : null}
    </div>
  );
}
