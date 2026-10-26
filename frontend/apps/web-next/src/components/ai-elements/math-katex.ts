/**
 * KaTeX for answers, loaded with the first answer that can contain math (see
 * `math.ts`): rehype-katex with the options both apps share, and its CSS.
 */
import { katexOptions } from "@eneo/markdown-math";
import rehypeKatex from "rehype-katex";
import type { Pluggable } from "unified";
import "katex/dist/katex.min.css";

export const rehypeTypesetMath: Pluggable = [rehypeKatex, katexOptions(false)];

/** For clipboard HTML, which cannot depend on the app's CSS: semantic MathML. */
export const rehypeTypesetMathAsMathml: Pluggable = [
  rehypeKatex,
  { ...katexOptions(false), output: "mathml" }
];
