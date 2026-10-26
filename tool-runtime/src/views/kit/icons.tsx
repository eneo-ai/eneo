/**
 * Glyphs the theme's icon set lacks, drawn from Lucide like the rest of it. Each is sized to
 * the text around it and hidden from assistive technology; the control it sits in has the name.
 */
import type { ReactNode } from "react";

function lucide(paths: ReactNode): ReactNode {
  return (
    <svg
      width="16"
      height="16"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      {paths}
    </svg>
  );
}

/** Angle brackets: source code. */
export const codeIcon = lucide(
  <>
    <polyline points="16 18 22 12 16 6" />
    <polyline points="8 6 2 12 8 18" />
  </>,
);
export const chevronDownIcon = lucide(<path d="m6 9 6 6 6-6" />);
/** An i in a circle: a note beside what it explains. */
export const infoIcon = lucide(
  <>
    <circle cx="12" cy="12" r="10" />
    <path d="M12 16v-4" />
    <path d="M12 8h.01" />
  </>,
);
export const chevronUpIcon = lucide(<path d="m18 15-6-6-6 6" />);
/** A triangle pointing right: run. */
export const playIcon = lucide(<polygon points="6 3 20 12 6 21 6 3" />);
/** An arrow turning back: undo what was changed. */
export const undoIcon = lucide(
  <>
    <path d="M3 12a9 9 0 1 0 9-9 9.75 9.75 0 0 0-6.74 2.74L3 8" />
    <path d="M3 3v5h5" />
  </>,
);
