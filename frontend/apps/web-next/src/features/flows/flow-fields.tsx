import type { ReactNode } from "react";
import { cn } from "@/lib/utils";

/** A labelled, read-only parameter row inside a step card or a run. */
export function Field({
  label,
  children,
  className
}: {
  label: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex flex-col gap-0.5", className)}>
      <dt className="text-ax-text-secondary text-[11px] font-semibold tracking-wide uppercase">
        {label}
      </dt>
      <dd className="text-ax-text m-0 min-w-0 text-[13px] leading-snug break-words">{children}</dd>
    </div>
  );
}

/** Verbatim text as the author wrote it (a prompt, a template, a schema). */
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

/** A small neutral chip: a step kind, an input, a file name. */
export function Chip({
  children,
  className,
  tone = "neutral"
}: {
  children: ReactNode;
  className?: string;
  tone?: "neutral" | "accent";
}) {
  return (
    <span
      className={cn(
        "inline-flex h-[22px] max-w-full items-center gap-1 rounded-full border px-2 text-[11.5px] font-medium whitespace-nowrap",
        tone === "accent"
          ? "bg-ax-accent-muted text-ax-text-accent border-transparent"
          : "border-ax-border bg-ax-surface text-ax-text-secondary",
        className
      )}
    >
      <span className="truncate">{children}</span>
    </span>
  );
}
