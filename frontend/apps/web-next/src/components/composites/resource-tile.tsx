"use client";

import { ClickableCard } from "@astryxdesign/core/ClickableCard";
import { List, ListItem } from "@astryxdesign/core/List";
import { Text } from "@astryxdesign/core/Text";
import { ChevronRight } from "lucide-react";
import { createContext, use, useRef } from "react";
import { useFocusAcrossLayouts } from "@/lib/hooks/use-focus-across-layouts";
import { PHONE_QUERY, useMediaMatch } from "@/lib/hooks/use-media-match";
import { cn } from "@/lib/utils";

/**
 * Grid for cards: as many columns as the room takes, each at least 17rem,
 * so the page's own width decides (a SideNav beside it narrows it), not the
 * window.
 */
export const RESOURCE_GRID_CLASS =
  "grid gap-3 grid-cols-[repeat(auto-fill,minmax(min(100%,17rem),1fr))]";

type ResourceLayout = "cards" | "rows";
const ResourceLayoutContext = createContext<ResourceLayout>("cards");

/** Whether the collection around shows rows (a phone) or cards. */
export function useResourceLayout(): ResourceLayout {
  return use(ResourceLayoutContext);
}

/**
 * A collection of resources (decision 9): list rows on a phone, cards from
 * 768 px. Its children are `ResourceCard`s (or items that read
 * `useResourceLayout`); each renders its own list item. CSS picks the
 * layout from the server render on; once the width is known, the other
 * goes. `trailing` (a create card) follows the cards, or the rows.
 *
 * Crossing 768 px (a phone turned) replaces every item, and an open menu or
 * dialog with it: the focus they had goes to the same resource's link in
 * the new layout (useFocusAcrossLayouts).
 */
export function ResourceCollection({
  children,
  trailing,
  gridClassName = RESOURCE_GRID_CLASS
}: {
  children: React.ReactNode;
  trailing?: React.ReactNode;
  gridClassName?: string;
}) {
  const phone = useMediaMatch(PHONE_QUERY);
  const box = useRef<HTMLDivElement>(null);
  useFocusAcrossLayouts(box, phone);

  return (
    <div ref={box} className="contents">
      {phone !== false ? (
        <div className="flex flex-col gap-3 md:hidden">
          <ResourceLayoutContext value="rows">
            <List hasDividers edge="outset">
              {children}
            </List>
          </ResourceLayoutContext>
          {trailing}
        </div>
      ) : null}
      {phone !== true ? (
        <ResourceLayoutContext value="cards">
          <ul className={cn(gridClassName, "max-md:hidden")}>
            {children}
            {trailing ? <li className="min-w-0">{trailing}</li> : null}
          </ul>
        </ResourceLayoutContext>
      ) : null}
    </div>
  );
}

export type ResourceCardProps = {
  /** The resource's main view (chat, run page, playground). */
  href: string;
  /** Visible title; also the accessible name of the card's link. */
  name: string;
  /** Leading tile, usually an `EntityAvatar`. Decorative next to the name. */
  tile: React.ReactNode;
  /** Status beside the tile, e.g. `<StatusLabel status="success" label="Publicerad" />`. */
  status?: React.ReactNode;
  /** At most two lines; when clamped, hovering shows the full text. */
  description?: React.ReactNode;
  /** Short metadata tokens under the description (model name, counts). */
  meta?: readonly string[];
  /** A menu trigger in the top corner. */
  actions?: React.ReactNode;
  className?: string;
};

/**
 * An assistant, app, service or space in a `ResourceCollection`, as a list
 * item of its own.
 *
 * As a card: tile and status on top, then the name, a clamped description
 * and metadata tokens. The whole card is one link (Astryx ClickableCard: a
 * named link inside, the surface clickable too). The actions sit on top of
 * the card as a sibling, not inside it: the legacy action menus render
 * portalled dialogs as their React children, and a click inside a portal
 * bubbles through the React tree, so inside ClickableCard a click on a
 * dialog's text would open the card's link.
 *
 * As a row (a phone): the tile, the name, then the status and description
 * on one line (the description wraps under a status it cannot fit beside,
 * at large text) and the tokens on the next; the menu at the end, or a
 * chevron where there is none (a menu with nothing the user may do renders
 * nothing). The whole row is the link (globals.css, section 12b), the menu
 * above it.
 */
export function ResourceCard({
  href,
  name,
  tile,
  status,
  description,
  meta,
  actions,
  className
}: ResourceCardProps) {
  const layout = useResourceLayout();

  if (layout === "rows") {
    const hasMeta = meta !== undefined && meta.length > 0;
    return (
      <ListItem
        href={href}
        className={className}
        label={<span className="block truncate font-semibold">{name}</span>}
        description={
          status || description || hasMeta ? (
            <span className="flex min-w-0 flex-col">
              {status || description ? (
                <span className="flex min-w-0 flex-wrap items-center gap-x-1.5">
                  {status ? (
                    <span className="flex max-w-full min-w-0 [&>span]:min-w-0 [&>span>span:last-child]:truncate">
                      {status}
                    </span>
                  ) : null}
                  {description ? (
                    <span className="min-w-[min(100%,8rem)] flex-1 truncate">{description}</span>
                  ) : null}
                </span>
              ) : null}
              {hasMeta ? <span className="truncate tabular-nums">{meta.join(" · ")}</span> : null}
            </span>
          ) : undefined
        }
        startContent={tile}
        endContent={
          <span className="flex items-center">
            <span className="peer contents">{actions}</span>
            <ChevronRight
              aria-hidden="true"
              className="text-ax-text-secondary hidden size-4 peer-empty:block"
            />
          </span>
        }
      />
    );
  }

  return (
    <li className="min-w-0">
      <div className={cn("relative h-full min-w-0", className)}>
        <ClickableCard
          href={href}
          label={name}
          padding={4}
          elevation="low"
          className="flex h-full min-w-0 flex-col gap-3"
        >
          <div className={cn("flex min-h-9 items-start gap-3", actions ? "pe-10" : null)}>
            {tile}
            {status ? <div className="ms-auto flex min-w-0 items-center pt-2">{status}</div> : null}
          </div>
          <div className="flex min-w-0 flex-col gap-1">
            <Text type="body" weight="bold" wordBreak="break-word">
              {name}
            </Text>
            {description ? (
              <Text as="p" type="body" color="secondary" maxLines={2}>
                {description}
              </Text>
            ) : null}
          </div>
          {meta && meta.length > 0 ? (
            <ul className="mt-auto flex flex-wrap gap-1.5">
              {meta.map((token, index) => (
                <li
                  key={`${index}-${token}`}
                  className="border-ax-border text-ax-text-secondary rounded-ax-inner inline-flex min-h-6 items-center border px-2 text-xs"
                >
                  {token}
                </li>
              ))}
            </ul>
          ) : null}
        </ClickableCard>
        {actions ? <div className="absolute end-2.5 top-2.5">{actions}</div> : null}
      </div>
    </li>
  );
}
