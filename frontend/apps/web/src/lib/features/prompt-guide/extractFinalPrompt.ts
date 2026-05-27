import { marked, type Token, type Tokens } from "marked";

/**
 * Extract the Prompt Guide's final, ready-to-use prompt from a markdown reply.
 *
 * The Prompt Guide is instructed (backend `defaults.py`) to emit the final
 * prompt as the *only* fenced code block in its reply, reserving fenced blocks
 * exclusively for that artifact. We therefore return the text of the **last**
 * fenced code block — or `null` while the guide is still interviewing (no
 * fenced block yet, so there is nothing to apply).
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
        codeBlocks.push((token as Tokens.Code).text ?? "");
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
    if (codeBlocks[i].trim().length > 0) return codeBlocks[i];
  }
  return null;
}
