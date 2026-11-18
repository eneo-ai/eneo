import type { Root } from "hast";
import { toText } from "hast-util-to-text";
import rehypeStringify from "rehype-stringify";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import { unified, type Pluggable } from "unified";
import { holdsMath, katexStore, remarkLlmMath } from "./math";
import { answerRehypePlugins, answerRemarkPlugins } from "./answer-markdown";

const clipboardParser = unified()
  .use(remarkParse)
  .use(answerRemarkPlugins)
  .use(remarkLlmMath)
  .use(remarkRehype, { allowDangerousHtml: true })
  .use(answerRehypePlugins);

/**
 * An answer for the clipboard: its plain text at once, its HTML on demand.
 * Clipboard HTML cannot depend on the app's CSS, so formulas become MathML;
 * consumers without MathML support still get the plain-text twin.
 */
export function renderAnswerForClipboard(markdown: string): {
  plainText: string;
  html: () => Promise<string>;
} {
  const tree = clipboardParser.runSync(clipboardParser.parse(markdown), markdown) as Root;
  return {
    // Read before formulas are typeset, so a plain-text paste holds each once.
    plainText: toText(tree).trim(),
    html: async () => {
      const finish = unified()
        .use(await mathmlSteps(tree))
        .use(rehypeStringify);
      return finish.stringify(finish.runSync(structuredClone(tree)) as Root);
    }
  };
}

/**
 * MathML typesetting for an answer that holds a formula. It waits for KaTeX
 * and fails without it, so a copy never silently carries formulas as code; an
 * answer without one (money, the word "math") copies without KaTeX.
 */
async function mathmlSteps(tree: Root): Promise<Pluggable[]> {
  if (!holdsMath(tree)) return [];
  await katexStore.load();
  const mathml = katexStore.mathml();
  if (!mathml) throw new Error("KaTeX could not be loaded for the copied formulas");
  return [mathml];
}
