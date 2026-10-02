import { proportional } from "@astryxdesign/core/Table";

const PX_PER_CHARACTER = 8;
/** Room for a cell's padding and a heading's sort mark. */
const AROUND = 40;
const NARROWEST = 72;
const WIDEST = 448;
/** Cells read to size a column; more would not change the answer much. */
const SAMPLED = 200;

const clamp = (characters: number) =>
  Math.min(WIDEST, Math.max(NARROWEST, characters * PX_PER_CHARACTER + AROUND));

/**
 * A column's share of the table: as much as its longest value asks for, up to a limit where
 * text wraps instead. It is never narrower than its heading or its longest word, so a table
 * with many columns scrolls sideways instead of squeezing them.
 */
export function columnWidth(header: string, cells: string[]) {
  let longest = header.length;
  let word = header.length;
  for (const cell of cells.slice(0, SAMPLED)) {
    longest = Math.max(longest, cell.length);
    for (const part of cell.split(/\s+/)) word = Math.max(word, part.length);
  }
  return proportional(clamp(longest), { minWidth: clamp(word) });
}
