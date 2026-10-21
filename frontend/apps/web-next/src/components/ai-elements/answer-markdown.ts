import { katexOptions } from "@eneo/markdown-math";
import type { Root } from "hast";
import { toText } from "hast-util-to-text";
import rehypeKatex from "rehype-katex";
import rehypeStringify from "rehype-stringify";
import remarkParse from "remark-parse";
import remarkRehype from "remark-rehype";
import { defaultRehypePlugins, defaultRemarkPlugins } from "streamdown";
import { unified } from "unified";
import { mathPlugin } from "./math";

// Keep Streamdown's GFM and sanitize/harden defaults in both the interactive
// answer and its clipboard representation. Math runs after sanitization.
export const answerRemarkPlugins = Object.values(defaultRemarkPlugins);
export const answerRehypePlugins = Object.values(defaultRehypePlugins);

const clipboardParser = unified()
  .use(remarkParse)
  .use(answerRemarkPlugins)
  .use([mathPlugin.remarkPlugin])
  .use(remarkRehype, { allowDangerousHtml: true })
  .use(answerRehypePlugins);

export function renderAnswerForClipboard(markdown: string): {
  html: string;
  plainText: string;
} {
  let plainText = "";
  const html = clipboardParser()
    .use(() => (tree: Root) => {
      // Read the sanitized content before KaTeX adds its visual and semantic
      // representations, so a plain-text paste contains each formula once.
      plainText = toText(tree).trim();
    })
    // Clipboard HTML cannot depend on the app's CSS. MathML is semantic;
    // consumers without MathML support still get the plain-text twin.
    .use(rehypeKatex, { ...katexOptions(false), output: "mathml" })
    .use(rehypeStringify)
    .processSync(markdown);
  return { html: String(html), plainText };
}
