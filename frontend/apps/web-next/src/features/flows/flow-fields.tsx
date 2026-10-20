import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/**
 * Verbatim text as the author wrote it (a prompt, a template, a schema).
 * Ours rather than Astryx's CodeBlock, which injects runtime styles the
 * production CSP blocks (see AGENTS.md → CSP).
 */
export function MonoBlock({ children, className }: { children: ReactNode; className?: string }) {
  return (
    <div
      className={cn(
        "bg-ax-sunken rounded-ax-inner max-h-80 overflow-auto px-2.5 py-2 font-mono text-[12.5px] leading-normal whitespace-pre-wrap",
        className
      )}
    >
      {children}
    </div>
  );
}
