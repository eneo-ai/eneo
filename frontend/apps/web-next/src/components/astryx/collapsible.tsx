import {
  Collapsible as AstryxCollapsible,
  type CollapsibleProps
} from "@astryxdesign/core/Collapsible";
import { useAnimatedLayout, type AnimatedLayout } from "@astryxdesign/core/hooks";
import { createContext, use, useState, type ReactNode, type RefObject } from "react";

export { CollapsibleGroup } from "@astryxdesign/core/Collapsible";

const AnimatedLayoutContext = createContext<AnimatedLayout | null>(null);

/**
 * The scroller whose content glides when a Collapsible in it opens or closes:
 * the page panel provides one. A Collapsible outside it, in a still scope, or
 * in a dialog or sheet (a portal), opens and closes at once.
 */
export function AnimatedLayoutScope({
  containerRef,
  children
}: {
  containerRef: RefObject<HTMLElement | null>;
  children: ReactNode;
}) {
  return (
    <AnimatedLayoutContext value={useAnimatedLayout({ containerRef })}>
      {children}
    </AnimatedLayoutContext>
  );
}

/**
 * Content whose disclosures open and close at once although a scope is above
 * it: the chat transcript, which follows an answer as it streams and must
 * never be moved by anything else.
 */
export function StillLayoutScope({ children }: { children: ReactNode }) {
  return <AnimatedLayoutContext value={null}>{children}</AnimatedLayoutContext>;
}

/**
 * Astryx Collapsible that takes its scroller's `animatedLayout` handle, so the
 * content after it glides instead of jumping and what it reveals clips open.
 * With reduced motion that is a short fade on touch and nothing with a mouse
 * (ACCESSIBILITY.md → Motion). Lint sends every Collapsible import here.
 */
export function Collapsible(props: CollapsibleProps) {
  return <AstryxCollapsible animatedLayout={use(AnimatedLayoutContext) ?? undefined} {...props} />;
}

/**
 * A controlled Collapsible whose content is costly to render: it is rendered on
 * the first open and then stays. Content that left on close could not glide out,
 * as the exit holds the element and not what the page renders into it, so the
 * panel would snap shut and everything below it jump.
 */
export function LazyCollapsible({
  isOpen,
  children,
  ...props
}: Omit<CollapsibleProps, "isOpen"> & { isOpen: boolean }) {
  const [opened, setOpened] = useState(isOpen);
  if (isOpen && !opened) setOpened(true);
  return (
    <Collapsible isOpen={isOpen} {...props}>
      {opened ? children : null}
    </Collapsible>
  );
}
