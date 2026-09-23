/**
 * How many unchanged steps in a row it takes before the Builder folds them
 * into one line. Two steps cost the reader a click to see what one extra row
 * would have shown, so a run that short stays open; the fold is for the long
 * flows it was built for. The planning screen and the review diagram fold the
 * same runs, so they read the rule from here.
 */
export const FOLD_MIN_RUN = 3;
