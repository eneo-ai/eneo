/**
 * Button kinds for tests of pages with no filled button, matched on the
 * `data-variant` both libraries render (Astryx's bare variant classes are
 * deprecated aliases, removed in 0.7.0).
 */

/** A filled button: shadcn's default or secondary, Astryx's primary or secondary. */
export const FILLED_BUTTONS =
  '[data-slot="button"]:is([data-variant="default"], [data-variant="secondary"]), .astryx-button:is([data-variant="primary"], [data-variant="secondary"])';

/**
 * A shadcn outline button, or an Astryx ghost one with a control-grade border
 * (Astryx has no outline variant; ACCESSIBILITY.md → Colour and contrast).
 */
export const isOutline = (button: HTMLElement) =>
  button.dataset.variant === "outline" ||
  (button.dataset.variant === "ghost" &&
    button.classList.contains("border") &&
    button.classList.contains("border-ax-border-control"));
