"use client";

import { Button } from "@astryxdesign/core/Button";
import { ChevronRight } from "lucide-react";
import { useId, useState, type ReactNode } from "react";

/** A publication group keeps its collapse state while filtering temporarily hides it. */
export function ResourceGroup({
  title,
  children,
  hidden = false
}: {
  title: string;
  children: ReactNode;
  hidden?: boolean;
}) {
  const id = useId();
  const [open, setOpen] = useState(true);
  if (hidden) return null;
  return (
    <section aria-labelledby={`${id}-heading`} className="flex flex-col gap-3">
      <h3 id={`${id}-heading`} className="text-ax-text-secondary text-sm font-semibold">
        <Button
          label={title}
          icon={<ChevronRight aria-hidden="true" className={open ? "rotate-90" : ""} />}
          variant="ghost"
          aria-expanded={open}
          aria-controls={`${id}-content`}
          onClick={() => setOpen(!open)}
        />
      </h3>
      <div id={`${id}-content`} hidden={!open}>
        {children}
      </div>
    </section>
  );
}
