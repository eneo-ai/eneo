/**
 * The Builder's one sheet width, shared by every screen, the phase rail and
 * the status rows, so the card edges never move as the work moves from the
 * task to the questions to the plan. Reading measures are capped inside each
 * screen instead (DESIGN.md caps prose at 64 to 72ch); the width is sized by
 * the Builder's own container, not the viewport. Tailwind reads the literals
 * from this file.
 */
export const BUILDER_COLUMN = {
  /** Every Builder screen. */
  sheet: "max-w-[70rem] @min-[110rem]:max-w-[76rem]"
} as const;

/** The measure a column of prose or a single-choice list reads at. */
export const BUILDER_MEASURE = "max-w-[46rem]";
