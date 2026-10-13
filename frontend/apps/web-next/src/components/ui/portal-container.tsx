"use client";

import { createContext, use } from "react";

/**
 * Where the legacy Radix popups (Select, DropdownMenu, Popover, Tooltip)
 * portal their content. Dialogs are native modal `<dialog>`s
 * (Astryx Dialog): they sit in the top layer and make the rest of the page
 * inert, so a popup portalled to `<body>` would open behind the dialog and
 * could not be used. A dialog provides its own element; `null` (the default)
 * keeps Radix's `<body>`.
 */
export const PortalContainerContext = createContext<HTMLElement | null>(null);

export function usePortalContainer(): HTMLElement | null {
  return use(PortalContainerContext);
}
