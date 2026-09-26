"use client";

import { ClickableCard } from "@astryxdesign/core/ClickableCard";
import { Text } from "@astryxdesign/core/Text";
import { cn } from "@/lib/utils";

/** Grid for `ResourceCard`s on a full-width space page (render it as a `<ul>`). */
export const RESOURCE_GRID_CLASS = "grid gap-3 sm:grid-cols-2 lg:grid-cols-3 2xl:grid-cols-4";

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
 * Card for an assistant, app, service or space in a grid: tile and status on
 * top, then the name, a clamped description and metadata tokens. The whole
 * card is one link (Astryx ClickableCard: a named link inside, the surface
 * clickable too).
 *
 * The actions sit on top of the card as a sibling, not inside it. The legacy
 * action menus render portalled dialogs as their React children, and a click
 * inside a portal bubbles through the React tree: inside ClickableCard, a
 * click on a dialog's text would open the card's link.
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
  return (
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
  );
}
