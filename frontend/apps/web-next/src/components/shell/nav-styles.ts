/**
 * Shared classes for SideNav item groups: the design's current-page weight
 * (Astryx selects with 500) and 44 px targets on touch layouts
 * (ACCESSIBILITY.md → Target size).
 */
export const NAV_ITEM_CLASSES =
  "[&_[aria-current=page]]:font-semibold pointer-coarse:[&_.astryx-side-nav-item]:min-h-11";

/** Rows the design sets in secondary text until they are the current page. */
export const SECONDARY_LINK_CLASSES = "[&_a:not([aria-current=page])]:text-ax-text-secondary";
