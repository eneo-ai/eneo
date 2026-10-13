import { Check } from "lucide-react";
import { cn } from "@/lib/utils";

const SIZE_CLASSES = {
  sm: "size-4 [&_svg]:size-2.5",
  md: "size-5 [&_svg]:size-3",
  lg: "size-7 [&_svg]:size-4"
} as const;

export type SuccessMarkProps = {
  size?: keyof typeof SIZE_CLASSES;
  /**
   * Replays the entrance when it changes (give it a counter that grows each
   * time the thing it marks lands), so the mark pops once per success and
   * then rests still. Omit for a static mark.
   */
  replayKey?: number | string;
  className?: string;
};

/**
 * A green check in a circle: the one "done" signal for a save that landed, a
 * job that finished, a file that became searchable. Decorative; the text
 * beside it carries the meaning. The entrance is a 300 ms zoom-and-fade that
 * the global reduced-motion rule turns off.
 */
export function SuccessMark({ size = "md", replayKey, className }: SuccessMarkProps) {
  return (
    <span
      key={replayKey}
      aria-hidden="true"
      data-success-mark=""
      className={cn(
        "bg-ax-success-muted text-ax-success inline-flex shrink-0 items-center justify-center rounded-full",
        replayKey !== undefined && "animate-in fade-in zoom-in-50 duration-300",
        SIZE_CLASSES[size],
        className
      )}
    >
      <Check strokeWidth={3} />
    </span>
  );
}
