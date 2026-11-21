import { Token } from "@astryxdesign/core/Token";
import type { ComponentProps, ReactNode } from "react";
import { cn } from "@/lib/utils";

type TokenColor = ComponentProps<typeof Token>["color"];

/**
 * A reference as a pill in running text (a message, an answer, the
 * composer): a small token centred on the line, never cut short by the
 * line's width. Its label is what the reference is called on the page.
 */
export function ReferenceToken({
  label,
  color,
  icon,
  className
}: {
  label: string;
  color?: TokenColor;
  icon?: ReactNode;
  className?: string;
}) {
  return (
    <Token
      size="sm"
      color={color}
      icon={icon}
      label={label}
      className={cn("max-w-none align-middle", className)}
    />
  );
}

/**
 * A pill the person presses: a native button around it, with the app's focus
 * ring. It wraps the pill tightly (inline-flex), so it has no text line of its
 * own to push the pill off the sentence's baseline or stretch the line. In
 * running text give it `align-middle`, as the pill inside has.
 */
export function PillButton({ className, children, ...props }: ComponentProps<"button">) {
  return (
    <button
      type="button"
      {...props}
      className={cn(
        "focus-visible:outline-ring rounded-ax-inner inline-flex focus-visible:outline-2 focus-visible:outline-offset-2",
        className
      )}
    >
      {children}
    </button>
  );
}
