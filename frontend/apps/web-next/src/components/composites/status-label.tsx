import { StatusDot } from "@astryxdesign/core/StatusDot";
import { cn } from "@/lib/utils";

export type StatusTone = "success" | "warning" | "error" | "accent" | "neutral";

export type StatusLabelProps = {
  status: StatusTone;
  /** Visible text; also what screen readers read (the dot is decorative). */
  label: string;
  /** Pulse the dot for live/in-progress states (respects reduced motion). */
  isPulsing?: boolean;
  className?: string;
};

/**
 * Coloured Astryx StatusDot plus its text, for statuses in lists, tables and
 * headers ("Publicerad", "Synkar…", "Fel"). Colour is never the only signal:
 * the label carries the meaning.
 *
 * @example
 * <StatusLabel status={published ? "success" : "neutral"} label={published ? t("published") : t("draft")} />
 */
export function StatusLabel({ status, label, isPulsing, className }: StatusLabelProps) {
  return (
    <span
      className={cn("text-ax-text-secondary inline-flex items-center gap-1.5 text-sm", className)}
    >
      <StatusDot variant={status} label={label} isPulsing={isPulsing} aria-hidden="true" />
      <span>{label}</span>
    </span>
  );
}
