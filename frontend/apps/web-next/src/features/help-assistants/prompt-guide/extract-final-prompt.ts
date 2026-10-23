import { findFencedCodeBlocks } from "./fenced-code-blocks";

const FINAL_PROMPT_LANGS = new Set([
  "",
  "prompt",
  "text",
  "markdown",
  "md",
  "system",
  "instructions"
]);

const MAX_FINAL_PROMPT_LENGTH = 100_000;

function isFinalPromptLang(lang: string): boolean {
  return FINAL_PROMPT_LANGS.has(lang.trim().toLowerCase());
}

/**
 * Extracts the final, ready-to-apply prompt from a Prompt Guide answer.
 * Interview-time `eneo-question` cards and arbitrary code snippets are ignored.
 */
export function extractFinalPrompt(markdown: string): string | null {
  if (markdown.trim().length === 0) return null;

  const blocks = findFencedCodeBlocks(markdown);
  for (let i = blocks.length - 1; i >= 0; i--) {
    const block = blocks[i];
    if (!block || !isFinalPromptLang(block.lang)) continue;
    if (block.body.trim().length === 0) continue;
    if (block.body.length > MAX_FINAL_PROMPT_LENGTH) continue;
    return block.body;
  }

  return null;
}
