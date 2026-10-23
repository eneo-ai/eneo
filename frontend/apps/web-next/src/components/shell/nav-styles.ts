/**
 * Shared classes for SideNav item groups: the design's current-page weight
 * (Astryx selects with 500). Touch layouts get 44 px items from the theme.
 */
export const NAV_ITEM_CLASSES = "[&_[aria-current=page]]:font-semibold";

/** Rows the design sets in secondary text until they are the current page. */
export const SECONDARY_LINK_CLASSES = "[&_a:not([aria-current=page])]:text-ax-text-secondary";
