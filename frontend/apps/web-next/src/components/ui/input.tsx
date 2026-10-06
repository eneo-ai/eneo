import * as React from "react";

import { cn } from "@/lib/utils";

/**
 * Focus ring for the legacy text fields: the full-strength ring over the
 * border, like Astryx fields (error colour while invalid). Inside an
 * InputGroup the group draws it around the whole field instead.
 */
export const FIELD_FOCUS_CLASSES =
  "focus-visible:outline-2 focus-visible:-outline-offset-1 focus-visible:outline-ring aria-invalid:border-destructive aria-invalid:focus-visible:outline-destructive data-[slot=input-group-control]:focus-visible:outline-none";

function Input({ className, type, ...props }: React.ComponentProps<"input">) {
  return (
    <input
      type={type}
      data-slot="input"
      className={cn(
        "border-input selection:bg-primary selection:text-primary-foreground file:text-foreground placeholder:text-muted-foreground dark:bg-input/30 h-9 w-full min-w-0 rounded-md border bg-transparent px-3 py-1 text-base shadow-xs transition-[color,box-shadow] file:inline-flex file:h-7 file:border-0 file:bg-transparent file:text-sm file:font-medium disabled:pointer-events-none disabled:cursor-not-allowed disabled:opacity-50 md:text-sm pointer-coarse:min-h-11",
        FIELD_FOCUS_CLASSES,
        className
      )}
      {...props}
    />
  );
}

export { Input };
