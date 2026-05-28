import { marked, type Token, type Tokens } from "marked";

/**
 * The Prompt Guide is instructed (backend `defaults.py`) to ask each
 * multi-choice question as a fenced code block whose language tag is
 * exactly `eneo-question` and whose body is a JSON envelope of this shape.
 * The frontend renders parsed envelopes as interactive cards in place of
 * the raw code block.
 */
export type PromptGuideOption = {
  label: string;
  description?: string;
};

export type PromptGuideQuestion = {
  header: string;
  question: string;
  multiSelect: boolean;
  options: PromptGuideOption[];
};

/**
 * Result of inspecting one assistant turn for a structured question:
 *
 * - `none` — no `eneo-question` block in the turn; render as plain markdown.
 * - `pending` — a `eneo-question` opener has streamed in but the closing
 *   fence hasn't arrived yet. Render `proseBefore` as markdown and show a
 *   "preparing a question" placeholder where the card will go.
 * - `invalid` — a closed `eneo-question` block whose JSON could not be
 *   parsed or whose shape failed validation. Render `proseBefore` and fall
 *   back to rendering the raw block as a normal code block via the standard
 *   markdown pipeline (call sites typically just re-render the whole turn
 *   text and let DOMPurify-sanitised markdown deal with it).
 * - `parsed` — a valid card. Render `proseBefore` as markdown, the card,
 *   then `proseAfter` as markdown.
 */
export type StructuredQuestionResult =
  | { kind: "none" }
  | { kind: "pending"; proseBefore: string }
  | { kind: "invalid"; proseBefore: string; proseAfter: string }
  | {
      kind: "parsed";
      proseBefore: string;
      question: PromptGuideQuestion;
      proseAfter: string;
    };

const QUESTION_LANG = "eneo-question";

// Length guards. A maliciously-prompt-injected or just confused model could
// emit a label of 10MB; the rule of thumb is "if it doesn't fit comfortably
// on a radio button, refuse to render". Sized to be generous for legitimate
// content and tight for nonsense.
//
// Options length rules:
// - 0 options is valid — that's the free-text intake mode (the card renders
//   only a single text field). The system prompt requires the first question
//   of every interview to be free-text.
// - 1 option is invalid — a single "choice" is not a choice.
// - 2..6 options is valid — multi-choice mode.
const LIMITS = {
  header: 100,
  question: 1000,
  label: 200,
  description: 500,
  minOptionsWhenChoice: 2,
  maxOptions: 6
} as const;

/**
 * Inspect an assistant turn's accumulated text for a structured question
 * block. Designed to be called on every streaming-chunk re-render, so it
 * tolerates partial input cleanly: a half-streamed `eneo-question` opener
 * resolves to `pending`, never to garbled card content.
 *
 * If multiple complete `eneo-question` blocks appear in a single turn (the
 * system prompt forbids this, but models occasionally over-share), only the
 * **last** is returned — that's the one the user is being asked to answer.
 */
export function extractStructuredQuestion(text: string): StructuredQuestionResult {
  if (!text || text.length === 0) return { kind: "none" };

  // Step 1 — strip a trailing unclosed `eneo-question` opener so the rest
  // of the parser only sees finalized blocks. A `code` token is only
  // emitted by marked once the closing fence arrives, so without this
  // guard a half-streamed block would simply be treated as a paragraph
  // (whose `raw` accidentally contains the partial JSON the user must not
  // see).
  const unclosed = findUnclosedQuestionOpener(text);
  if (unclosed !== null) {
    return { kind: "pending", proseBefore: text.slice(0, unclosed) };
  }

  // Step 2 — lex the stable portion and find the LAST `eneo-question`
  // code block. Position is reconstructed by accumulating `raw` lengths;
  // marked's lexer guarantees the sum of `raw` over the top-level tokens
  // equals the input string.
  let tokens: Token[];
  try {
    tokens = marked.lexer(text);
  } catch {
    return { kind: "none" };
  }

  let cursor = 0;
  let lastBlock: { start: number; raw: string; body: string } | null = null;
  for (const token of tokens) {
    const raw = (token as { raw?: string }).raw ?? "";
    if (
      token.type === "code" &&
      (token as Tokens.Code).lang?.trim().toLowerCase() === QUESTION_LANG
    ) {
      lastBlock = {
        start: cursor,
        raw,
        body: (token as Tokens.Code).text ?? ""
      };
    }
    cursor += raw.length;
  }

  if (lastBlock === null) return { kind: "none" };

  const proseBefore = text.slice(0, lastBlock.start);
  const proseAfter = text.slice(lastBlock.start + lastBlock.raw.length);
  const parsed = parseAndValidate(lastBlock.body);

  if (parsed === null) {
    return { kind: "invalid", proseBefore, proseAfter };
  }

  return { kind: "parsed", proseBefore, question: parsed, proseAfter };
}

/**
 * Returns the byte offset of the last `eneo-question` opener that has no
 * matching closing fence after it, or `null` if every opener is closed.
 *
 * Line-based scan: an opener is a line whose trimmed-trailing form is
 * exactly ```` ```eneo-question ````, a closer is a line whose
 * trimmed-trailing form is exactly ```` ``` ````. This mirrors the LLM's
 * actual output convention; deeper edge cases (nested four-backtick
 * fences) are intentionally not handled — the system prompt forbids them.
 */
function findUnclosedQuestionOpener(text: string): number | null {
  const lines = text.split("\n");
  for (let i = lines.length - 1; i >= 0; i--) {
    if (lines[i].trimEnd() !== "```" + QUESTION_LANG) continue;
    for (let j = i + 1; j < lines.length; j++) {
      if (lines[j].trimEnd() === "```") return null;
    }
    // Compute the byte offset of the start of line i.
    let offset = 0;
    for (let k = 0; k < i; k++) offset += lines[k].length + 1; // +1 for the \n
    return offset;
  }
  return null;
}

function parseAndValidate(body: string): PromptGuideQuestion | null {
  let raw: unknown;
  try {
    raw = JSON.parse(body);
  } catch {
    return null;
  }

  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const r = raw as Record<string, unknown>;

  if (!isBoundedString(r.header, LIMITS.header)) return null;
  if (!isBoundedString(r.question, LIMITS.question)) return null;
  if (typeof r.multiSelect !== "boolean") return null;
  if (!Array.isArray(r.options)) return null;
  // 0 options = free-text intake mode; 2..6 = multi-choice; anything else
  // (notably 1) is malformed.
  if (r.options.length === 1 || r.options.length > LIMITS.maxOptions) return null;
  if (r.options.length > 0 && r.options.length < LIMITS.minOptionsWhenChoice) return null;

  const options: PromptGuideOption[] = [];
  for (const opt of r.options) {
    if (!opt || typeof opt !== "object" || Array.isArray(opt)) return null;
    const o = opt as Record<string, unknown>;
    if (!isBoundedString(o.label, LIMITS.label)) return null;

    let description: string | undefined;
    if (o.description !== undefined && o.description !== null) {
      if (typeof o.description !== "string") return null;
      if (o.description.length > LIMITS.description) return null;
      // Empty description string is allowed (some LLMs emit `"description":""`
      // when they have nothing extra to say); collapse to undefined so the
      // renderer doesn't reserve space for a blank line.
      description = o.description.length > 0 ? o.description : undefined;
    }
    options.push({ label: (o.label as string).trim(), description });
  }

  return {
    header: (r.header as string).trim(),
    question: (r.question as string).trim(),
    multiSelect: r.multiSelect,
    options
  };
}

function isBoundedString(value: unknown, maxLen: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= maxLen;
}
