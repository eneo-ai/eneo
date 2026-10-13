import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { Loader2 } from "lucide-react";
import { Slot } from "radix-ui";

import { cn } from "@/lib/utils";

/*
 * Legacy shadcn button, kept to WCAG 2.2 AA (ACCESSIBILITY.md → Visible focus,
 * Target size, Colour and contrast): the full-strength focus ring, hover
 * tints that keep the label's contrast (bg-ax-hover-overlay, globals.css) and
 * 44 px targets on a coarse pointer.
 */
const buttonVariants = cva(
  "inline-flex shrink-0 items-center justify-center gap-2 rounded-md text-sm font-medium whitespace-nowrap transition-all focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-ring disabled:pointer-events-none disabled:opacity-50 aria-invalid:border-destructive pointer-coarse:min-h-11 [&_svg]:pointer-events-none [&_svg]:shrink-0 [&_svg:not([class*='size-'])]:size-4",
  {
    variants: {
      variant: {
        default: "bg-primary text-primary-foreground hover:bg-ax-hover-overlay",
        destructive:
          "bg-destructive text-destructive-foreground hover:bg-ax-hover-overlay focus-visible:outline-destructive",
        outline:
          "border bg-background shadow-xs hover:bg-accent hover:text-accent-foreground dark:border-input dark:bg-input/30 dark:hover:bg-input/50",
        secondary: "bg-secondary text-secondary-foreground hover:bg-ax-hover-overlay",
        ghost: "hover:bg-accent hover:text-accent-foreground dark:hover:bg-accent/50",
        link: "text-ax-text-accent underline-offset-4 hover:underline"
      },
      size: {
        default: "h-9 px-4 py-2 has-[>svg]:px-3",
        xs: "h-6 gap-1 rounded-md px-2 text-xs has-[>svg]:px-1.5 [&_svg:not([class*='size-'])]:size-3",
        sm: "h-8 gap-1.5 rounded-md px-3 has-[>svg]:px-2.5",
        lg: "h-10 rounded-md px-6 has-[>svg]:px-4",
        icon: "size-9 pointer-coarse:min-w-11",
        "icon-xs": "size-6 rounded-md pointer-coarse:min-w-11 [&_svg:not([class*='size-'])]:size-3",
        "icon-sm": "size-8 pointer-coarse:min-w-11",
        "icon-lg": "size-10 pointer-coarse:min-w-11"
      }
    },
    defaultVariants: {
      variant: "default",
      size: "default"
    }
  }
);

function Button({
  className,
  variant = "default",
  size = "default",
  asChild = false,
  children,
  ...props
}: React.ComponentProps<"button"> &
  VariantProps<typeof buttonVariants> & {
    asChild?: boolean;
  }) {
  const Comp = asChild ? Slot.Root : "button";
  // A busy button stays enabled so it keeps focus (ACCESSIBILITY.md → Forms);
  // the spinner shows sighted users what aria-busy tells assistive tech. Not
  // for icon buttons, whose fixed size has no room for it, nor asChild.
  const busy =
    !asChild &&
    !size?.startsWith("icon") &&
    (props["aria-busy"] === true || props["aria-busy"] === "true");

  return (
    <Comp
      data-slot="button"
      data-variant={variant}
      data-size={size}
      className={cn(buttonVariants({ variant, size, className }), busy && "cursor-progress")}
      {...props}
    >
      {busy ? (
        <>
          <Loader2 aria-hidden="true" className="motion-safe:animate-spin" />
          {children}
        </>
      ) : (
        // Untouched: asChild's Slot takes exactly one child.
        children
      )}
    </Comp>
  );
}

export { Button, buttonVariants };
