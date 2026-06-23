import { marked, type Token, type Tokens } from "marked";

/**
 * Language tags accepted as a "final prompt" code block.
 *
 * The Prompt Guide is instructed (backend `defaults.py`) to emit the final
 * prompt as an *untagged* fenced code block, but the model occasionally
 * reaches for a benign synonym (`prompt`, `text`, `markdown`, …). We accept
 * the synonyms it has been known to pick and reject everything else so a
 * stray ```` ```json ```` or ```` ```eneo-question ```` block can never be
 * confused for the artifact.
 *
 * Comparison is case-insensitive after `.trim()`.
 */
const FINAL_PROMPT_LANGS = new Set([
  "",
  "prompt",
  "text",
  "markdown",
  "md",
  "system",
  "instructions"
]);

function isFinalPromptLang(lang: string | undefined | null): boolean {
  return FINAL_PROMPT_LANGS.has((lang ?? "").trim().toLowerCase());
}

/**
 * Upper bound on the applied prompt. A prompt-injected or simply confused
 * model could emit a multi-megabyte fenced block; oversized blocks are
 * skipped rather than returned. Mirrors the backend `question` max_length so
 * the round-trip (apply -> save -> next run) stays within the same envelope.
 */
const MAX_FINAL_PROMPT_LENGTH = 100_000;

/**
 * Extract the Prompt Guide's final, ready-to-use prompt from a markdown reply.
 *
 * Returns the text of the **last** fenced code block whose language tag is
 * in {@link FINAL_PROMPT_LANGS} — or `null` while the guide is still
 * interviewing (no qualifying fenced block yet, so there is nothing to apply).
 * Tagged blocks the Prompt Guide uses for other purposes (notably
 * `eneo-question` cards) are skipped, as are blocks tagged with arbitrary
 * code-fence languages (`json`, `yaml`, `python`, …).
 *
 * Inline code (`codespan`) is ignored on purpose: only fenced ```` ``` ````
 * blocks count, so a stray backtick in a question never looks applicable.
 */
export function extractFinalPrompt(markdown: string): string | null {
  if (!markdown || markdown.trim().length === 0) return null;

  let tokens: Token[];
  try {
    tokens = marked.lexer(markdown);
  } catch {
    return null;
  }

  const codeBlocks: string[] = [];

  const collect = (nodes: Token[] | undefined): void => {
    if (!nodes) return;
    for (const token of nodes) {
      if (token.type === "code") {
        const codeToken = token as Tokens.Code;
        if (isFinalPromptLang(codeToken.lang)) {
          codeBlocks.push(codeToken.text ?? "");
        }
      }
      // Recurse into containers that may wrap a fenced block (blockquotes,
      // paragraphs, list items) so the artifact is found regardless of nesting.
      collect((token as { tokens?: Token[] }).tokens);
      if (token.type === "list") {
        for (const item of (token as Tokens.List).items) {
          collect(item.tokens);
        }
      }
    }
  };

  collect(tokens);

  for (let i = codeBlocks.length - 1; i >= 0; i--) {
    const block = codeBlocks[i];
    if (block.trim().length === 0) continue;
    if (block.length > MAX_FINAL_PROMPT_LENGTH) continue;
    return block;
  }
  return null;
}
