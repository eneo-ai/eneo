import { createDropdownMenu, type DropdownMenu } from "@melt-ui/svelte";
import { getContext, setContext } from "svelte";

const ctxKey = "dropdown";

export function createDropdown(
  placement: "bottom" | "bottom-start" | "bottom-end" = "bottom",
  arrowSize = 12,
  gutter = 5
): DropdownMenu {
  const ctx = createDropdownMenu({
    positioning: {
      fitViewport: true,
      flip: true,
      placement,
      gutter
    },
    forceVisible: true,
    loop: true,
    preventScroll: true,
    arrowSize
  });

  setContext<DropdownMenu>(ctxKey, ctx);
  return ctx;
}

export function getDropdown(): DropdownMenu {
  return getContext<DropdownMenu>(ctxKey);
}
