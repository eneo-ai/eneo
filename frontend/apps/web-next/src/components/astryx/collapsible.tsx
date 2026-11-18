import {
  Collapsible as AstryxCollapsible,
  type CollapsibleProps
} from "@astryxdesign/core/Collapsible";
import { useAnimatedLayout, type AnimatedLayout } from "@astryxdesign/core/hooks";
import { createContext, use, type ReactNode, type RefObject } from "react";

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
