import { cn } from "$lib/utils.js";

// The `data-[size=default]:` twins override AlertDialog's own size-scoped max widths, which are
// more specific than a plain `sm:max-w-*`.
const widths = {
  small: "sm:max-w-md data-[size=default]:sm:max-w-md",
  medium: "sm:max-w-2xl data-[size=default]:sm:max-w-2xl",
  large: "sm:max-w-5xl data-[size=default]:sm:max-w-5xl",
  dynamic: "w-fit sm:max-w-[80vw] data-[size=default]:sm:max-w-[80vw]"
} as const;

export type DialogWidth = keyof typeof widths;

/**
 * Shared layout for shadcn `Dialog`/`AlertDialog`: a fixed header and footer around a scrolling
 * body, so long forms stay usable in a height-capped dialog.
 *
 * A viewport 30rem tall or less (a phone in landscape, or 400 % zoom at about 320 × 256 px) has
 * no room for a fixed header and footer, which would leave the body a sliver or clip it. There
 * the whole dialog scrolls instead.
 */
export const dialogLayout = {
  content: (width: DialogWidth = "small", className?: string) =>
    cn(
      "flex max-h-[calc(100dvh-2rem)] max-w-[calc(100%-2rem)] flex-col gap-0 overflow-hidden p-0 data-[size=default]:max-w-[calc(100%-2rem)] sm:max-h-[85dvh] [@media(max-height:30rem)]:overflow-y-auto",
      widths[width],
      className
    ),
  header: "shrink-0 gap-1.5 border-b px-6 py-4 pr-12",
  body: "flex min-h-0 flex-1 flex-col gap-4 overflow-y-auto px-6 py-5 [@media(max-height:30rem)]:flex-none [@media(max-height:30rem)]:overflow-visible",
  section: "flex flex-col rounded-lg border",
  footer: "mx-0 mb-0 shrink-0 rounded-none border-t px-6 py-4"
};
