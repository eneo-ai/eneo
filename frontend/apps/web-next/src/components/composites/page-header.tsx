import { BreadcrumbItem, Breadcrumbs } from "@astryxdesign/core/Breadcrumbs";
import { Heading } from "@astryxdesign/core/Heading";
import { Text } from "@astryxdesign/core/Text";
import { cn } from "@/lib/utils";

export type PageHeaderCrumb = {
  label: string;
  /** Link target. Without one the crumb is plain text, such as an admin section. */
  href?: string;
  /** The crumb is this page (`aria-current="page"`, never a link). */
  current?: boolean;
};

export type PageHeaderProps = {
  /** The page's h1. */
  title: string;
  /** One-line summary under the title. */
  description?: string;
  /**
   * Ancestor trail above the title, root first. Crumbs with `href` are links,
   * crumbs without one are plain labels; only a crumb with `current` is
   * announced as the current page. Skip on top-level pages.
   */
  breadcrumbs?: readonly PageHeaderCrumb[];
  /** Page-level actions (buttons, save status), right-aligned; wraps on narrow screens. */
  actions?: React.ReactNode;
  /** Legacy actions slot — same as `actions`, which wins when both are set. */
  children?: React.ReactNode;
  /** `data-tour` anchor for the guided tour. */
  tour?: string;
  className?: string;
};

/**
 * Page title block: optional breadcrumbs, h1, optional description and an
 * actions slot. Server-component safe (Astryx parts are client components).
 *
 * @example
 * <PageHeader
 *   title={membersTitle}
 *   breadcrumbs={[{ label: spacesLabel, href: "/spaces" }, { label: space.name, href: spaceHref }]}
 *   description={membersIntro}
 *   actions={<AddMemberDialog />}
 * />
 */
export function PageHeader({
  title,
  description,
  breadcrumbs,
  actions,
  children,
  tour,
  className
}: PageHeaderProps) {
  const actionSlot = actions ?? children;

  return (
    <div data-tour={tour} className={cn("flex flex-col gap-2", className)}>
      {breadcrumbs && breadcrumbs.length > 0 ? (
        <Breadcrumbs variant="supporting">
          {breadcrumbs.map((crumb, index) => (
            <BreadcrumbItem
              key={`${index}-${crumb.href ?? crumb.label}`}
              href={crumb.current ? undefined : crumb.href}
              // Explicit false: Astryx would otherwise mark the last crumb current.
              isCurrent={crumb.current ?? false}
            >
              {crumb.label}
            </BreadcrumbItem>
          ))}
        </Breadcrumbs>
      ) : null}
      <div className="flex min-h-9 flex-wrap items-center justify-between gap-x-4 gap-y-2">
        <div className="flex min-w-0 flex-col gap-1">
          <Heading level={1} className="break-words">
            {title}
          </Heading>
          {description ? (
            <Text as="p" type="body" color="secondary">
              {description}
            </Text>
          ) : null}
        </div>
        {actionSlot ? <div className="flex flex-wrap items-center gap-2">{actionSlot}</div> : null}
      </div>
    </div>
  );
}
