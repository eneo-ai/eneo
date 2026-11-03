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
  /** The page's h1 (or h2, see `headingLevel`). */
  title: string;
  /**
   * Outline level of the title. 1 (default) for a page's own heading; 2 for a
   * page inside a frame that already renders the h1, such as a space tab.
   */
  headingLevel?: 1 | 2;
  /**
   * Id for the title heading, so the page's main table or region can take the
   * title as its name (`aria-labelledby`).
   */
  headingId?: string;
  /**
   * Ref to the title heading. Setting it also makes the heading a programmatic
   * focus target (`tabIndex={-1}`), e.g. for focus after a delete removed the
   * focused row (`RemovalFocusScope`).
   */
  headingRef?: React.Ref<HTMLHeadingElement>;
  /** One-line summary under the title. */
  description?: React.ReactNode;
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
  /**
   * A space tab on a phone, where the active tab of the space's strip already
   * names the page: on a phone's layout (`phone:`) the title and description
   * stay for screen readers only and the header takes no room in the page. Its actions are
   * expected to be `DockedActions`, fixed at the bottom there.
   */
  isTitleHiddenOnPhone?: boolean;
  className?: string;
};

/**
 * Astryx draws the crumb link 25 px tall; a thumb needs the full touch size.
 * The text stays at the start, on the title's line; a short crumb's spare width
 * falls after it.
 */
export const CRUMB_TOUCH = "pointer-coarse:[&>a]:min-h-11 pointer-coarse:[&>a]:min-w-11";

/**
 * Page title block: optional breadcrumbs, h1 (or h2), optional description
 * and an actions slot. Server-component safe (Astryx parts are client
 * components; `headingRef` is for client callers).
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
  headingLevel = 1,
  headingId,
  headingRef,
  description,
  breadcrumbs,
  actions,
  children,
  tour,
  isTitleHiddenOnPhone = false,
  className
}: PageHeaderProps) {
  const actionSlot = actions ?? children;
  // A pushed screen's page bar says the same ("‹ Administration"): it replaces the trail
  // below 1024 px, or on a phone's layout on a space's pages.

  return (
    <div
      data-tour={tour}
      className={cn("flex flex-col gap-2", isTitleHiddenOnPhone && "phone:contents", className)}
    >
      {breadcrumbs && breadcrumbs.length > 0 ? (
        <Breadcrumbs
          variant="supporting"
          className="phone:group-has-[[data-own-phone-header]]/shell:hidden group-has-[[data-own-mobile-header]]/shell:max-lg:hidden"
        >
          {breadcrumbs.map((crumb, index) => (
            <BreadcrumbItem
              key={`${index}-${crumb.href ?? crumb.label}`}
              href={crumb.current ? undefined : crumb.href}
              // Explicit false: Astryx would otherwise mark the last crumb current.
              isCurrent={crumb.current ?? false}
              className={CRUMB_TOUCH}
            >
              {crumb.label}
            </BreadcrumbItem>
          ))}
        </Breadcrumbs>
      ) : null}
      <div
        className={cn(
          "flex min-h-9 flex-wrap justify-between gap-x-4 gap-y-2",
          // Under a description the actions stand on the title's line, not halfway
          // down the paragraph (a three-line one put "Skapa roll" beside its middle).
          description ? "items-start" : "items-center",
          isTitleHiddenOnPhone && "phone:contents"
        )}
      >
        <div className={cn("flex min-w-0 flex-col gap-1", isTitleHiddenOnPhone && "phone:sr-only")}>
          <Heading
            level={headingLevel}
            id={headingId}
            className={cn(
              "break-words",
              headingRef &&
                "focus-visible:outline-ring rounded-ax-inner focus-visible:outline-2 focus-visible:outline-offset-2"
            )}
            {...(headingRef ? { ref: headingRef, tabIndex: -1 } : {})}
          >
            {title}
          </Heading>
          {description ? (
            <Text as="p" type="body" color="secondary" className="max-w-prose">
              {description}
            </Text>
          ) : null}
        </div>
        {actionSlot ? (
          <div
            className={cn(
              "flex flex-wrap items-center gap-2",
              isTitleHiddenOnPhone && "phone:contents"
            )}
          >
            {actionSlot}
          </div>
        ) : null}
      </div>
    </div>
  );
}
