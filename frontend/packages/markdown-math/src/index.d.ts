export function canOpenDollar(prev: string | undefined, next: string | undefined): boolean;
export function canFollowWithDollar(prev: string | undefined): boolean;
export function canCloseDollar(prev: string | undefined, next: string | undefined): boolean;

export interface MathKatexOptions {
  displayMode: boolean;
  throwOnError: false;
  trust: false;
  strict: "ignore";
  maxSize: number;
  maxExpand: number;
  output: "htmlAndMathml";
}

export function katexOptions(displayMode: boolean): MathKatexOptions;

/** One rendered formula: display or inline, and its TeX source. */
export interface MathCaseFormula {
  display: boolean;
  tex: string;
}

/**
 * One answer and what the chat must show for it. `math` lists every formula in
 * order; `literal` are texts that must appear as written (proving they were
 * not rendered as math), with each run of whitespace, line breaks included,
 * read as one space; `href` is a link destination that must survive unchanged.
 */
export interface MathCase {
  name: string;
  input: string;
  math: MathCaseFormula[];
  literal?: string[];
  href?: string;
}
