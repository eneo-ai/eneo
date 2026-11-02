import { Heading } from "@astryxdesign/core/Heading";
import Link from "@/lib/link";
import { Plus } from "lucide-react";
import { useRef } from "react";
import { cn } from "@/lib/utils";
import { RemovalFocusScope } from "../removal";

/** "Visa alla" and friends: a standalone text link with a 24 px target. */
export function OverviewLink({
  href,
  children,
  label
}: {
  href: string;
  children: React.ReactNode;
  /** Fuller accessible name that starts with the visible text ("Visa alla assistenter"). */
  label?: string;
}) {
  return (
    <Link
      href={href}
      aria-label={label}
      className="text-ax-text-accent focus-visible:outline-ring rounded-ax-inner inline-flex min-h-6 items-center text-sm font-semibold hover:underline focus-visible:outline-2 focus-visible:outline-offset-2 pointer-coarse:min-h-11"
    >
      {children}
    </Link>
  );
}

/**
 * A titled block on the space overview: h2, optional end content, body. When
 * a row inside is deleted or moved away, focus goes to the heading.
 */
export function OverviewSection({
  id,
  title,
  end,
  children,
  className
}: {
  id: string;
  title: string;
  end?: React.ReactNode;
  children: React.ReactNode;
  className?: string;
}) {
  const headingRef = useRef<HTMLHeadingElement>(null);
  return (
    <RemovalFocusScope target={headingRef}>
      <section aria-labelledby={id} className={cn("flex min-w-0 flex-col gap-3", className)}>
        <div className="flex min-h-8 flex-wrap items-center justify-between gap-x-3 gap-y-2">
          <Heading
            ref={headingRef}
            level={2}
            id={id}
            tabIndex={-1}
            className="focus-visible:outline-ring rounded-ax-inner text-base leading-snug font-bold focus-visible:outline-2 focus-visible:outline-offset-2"
          >
            {title}
          </Heading>
          {end ? <div className="flex flex-wrap items-center gap-3">{end}</div> : null}
        </div>
        {children}
      </section>
    </RemovalFocusScope>
  );
}

/**
 * Dashed card that starts a create flow: its hint and the flow's own control
 * (a split button or a button), so the card itself needs no click handling.
 * Where a screen is narrow the control moves into the section's heading
 * instead (a phone): a card as tall as an assistant is not worth the room.
 */
export function OverviewCreateCard({ hint, action }: { hint: string; action: React.ReactNode }) {
  return (
    <div className="border-ax-border-strong rounded-ax-container flex h-full min-h-40 flex-col items-center justify-center gap-3 border border-dashed p-4 text-center">
      <span
        aria-hidden="true"
        className="bg-ax-muted text-ax-text flex size-9 items-center justify-center rounded-full"
      >
        <Plus className="size-4.5" />
      </span>
      <p className="text-ax-text-secondary text-sm">{hint}</p>
      {action}
    </div>
  );
}
