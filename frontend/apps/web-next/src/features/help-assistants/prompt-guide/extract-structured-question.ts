import { findFencedCodeBlocks, findUnclosedFenceOpener } from "./fenced-code-blocks";

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
const FALLBACK_LANGS = new Set(["question", "json"]);

const LIMITS = {
  header: 100,
  question: 1000,
  label: 200,
  description: 500,
  minOptionsWhenChoice: 2,
  maxOptions: 6
} as const;

export function extractStructuredQuestion(text: string): StructuredQuestionResult {
  if (text.length === 0) return { kind: "none" };

  const unclosed = findUnclosedFenceOpener(text, QUESTION_LANG);
  if (unclosed !== null) {
    return { kind: "pending", proseBefore: text.slice(0, unclosed) };
  }

  const blocks = findFencedCodeBlocks(text);
  const canonicalBlocks = blocks.filter(
    (block) => block.lang.trim().toLowerCase() === QUESTION_LANG
  );
  const lastCanonicalBlock = canonicalBlocks[canonicalBlocks.length - 1];

  if (lastCanonicalBlock) {
    const proseBefore = text.slice(0, lastCanonicalBlock.start);
    const proseAfter = text.slice(lastCanonicalBlock.start + lastCanonicalBlock.raw.length);
    const parsed = parseAndValidate(lastCanonicalBlock.body);
    return parsed === null
      ? { kind: "invalid", proseBefore, proseAfter }
      : { kind: "parsed", proseBefore, question: parsed, proseAfter };
  }

  for (let i = blocks.length - 1; i >= 0; i--) {
    const block = blocks[i];
    if (!block || !FALLBACK_LANGS.has(block.lang.trim().toLowerCase())) continue;

    const parsed = parseAndValidate(block.body);
    if (parsed !== null) {
      const proseBefore = text.slice(0, block.start);
      const proseAfter = text.slice(block.start + block.raw.length);
      return { kind: "parsed", proseBefore, question: parsed, proseAfter };
    }
  }

  return { kind: "none" };
}

function parseAndValidate(body: string): PromptGuideQuestion | null {
  let raw: unknown;
  try {
    raw = JSON.parse(body);
  } catch {
    raw = tryRepairAndParse(body);
    if (raw === undefined) return null;
  }

  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return null;
  const candidate = raw as Record<string, unknown>;

  if (!isBoundedString(candidate.header, LIMITS.header)) return null;
  if (!isBoundedString(candidate.question, LIMITS.question)) return null;
  if (typeof candidate.multiSelect !== "boolean") return null;
  if (!Array.isArray(candidate.options)) return null;
  if (candidate.options.length === 1 || candidate.options.length > LIMITS.maxOptions) return null;
  if (candidate.options.length > 0 && candidate.options.length < LIMITS.minOptionsWhenChoice) {
    return null;
  }

  const options: PromptGuideOption[] = [];
  for (const option of candidate.options) {
    if (!option || typeof option !== "object" || Array.isArray(option)) return null;
    const optionCandidate = option as Record<string, unknown>;
    if (!isBoundedString(optionCandidate.label, LIMITS.label)) return null;

    let description: string | undefined;
    if (optionCandidate.description !== undefined && optionCandidate.description !== null) {
      if (typeof optionCandidate.description !== "string") return null;
      if (optionCandidate.description.length > LIMITS.description) return null;
      description =
        optionCandidate.description.length > 0 ? optionCandidate.description : undefined;
    }
    options.push({ label: optionCandidate.label.trim(), description });
  }

  return {
    header: candidate.header.trim(),
    question: candidate.question.trim(),
    multiSelect: candidate.multiSelect,
    options
  };
}

function isBoundedString(value: unknown, maxLen: number): value is string {
  return typeof value === "string" && value.trim().length > 0 && value.length <= maxLen;
}

function tryRepairAndParse(body: string): unknown {
  const repaired = body
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .replace(/,(\s*[}\]])/g, "$1");

  try {
    return JSON.parse(repaired);
  } catch {
    return undefined;
  }
}
