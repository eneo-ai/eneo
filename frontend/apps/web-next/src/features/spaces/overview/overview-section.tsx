import { Heading } from "@astryxdesign/core/Heading";
import { useRef } from "react";
import { cn } from "@/lib/utils";
import { RemovalFocusScope } from "../removal";

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
