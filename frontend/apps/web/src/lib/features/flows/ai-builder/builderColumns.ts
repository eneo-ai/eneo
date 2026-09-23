/**
 * The Builder's reading columns, one owner for the widths each screen, the
 * phase rail and the status rows share (DESIGN.md: 41.25, 43.75 and 53.75rem,
 * about 10% wider at 2xl). Tailwind reads these literals from this file.
 */
export const BUILDER_COLUMN = {
  /** The first task prompt. */
  task: "max-w-[40.625rem] 2xl:max-w-[45rem]",
  /** One question or a reply. */
  question: "max-w-[41.25rem] 2xl:max-w-[45.625rem]",
  /** Confirm, build, findings, repair and the conversation. */
  standard: "max-w-[43.75rem] 2xl:max-w-[48.125rem]",
  /** The plan review. */
  review: "max-w-[53.75rem] 2xl:max-w-[62.5rem]"
} as const;
