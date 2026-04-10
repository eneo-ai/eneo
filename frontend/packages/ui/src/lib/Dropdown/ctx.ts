import { createDropdownMenu } from "@melt-ui/svelte";
import { getContext, setContext } from "svelte";

type DropdownCtx = ReturnType<typeof createDropdownMenu>;

const ctxKey = "dropdown";

export function createDropdown(
  placement: "bottom" | "bottom-start" | "bottom-end" = "bottom",
  arrowSize = 12,
  gutter = 5
): DropdownCtx {
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

  setContext<typeof ctx>(ctxKey, ctx);
  return ctx;
}

export function getDropdown(): DropdownCtx {
  return getContext<DropdownCtx>(ctxKey);
}
