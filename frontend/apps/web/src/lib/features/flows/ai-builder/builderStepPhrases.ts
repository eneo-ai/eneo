import { m } from "$lib/paraglide/messages";
import { getLocale } from "$lib/paraglide/runtime";
import { parseFlowInputBindings } from "$lib/features/flows/flowInputBindings";
import {
  extractTemplateTokens,
  TEMPLATE_TOKEN_PATTERN_SOURCE
} from "$lib/features/flows/flowVariableTokens";
import type { StepSpec } from "./protocol";

/**
 * The words the Builder uses for what a step reads and what it answers with,
 * shared by the review's change summary, the diagram and the task screen so a
 * step is described the same way everywhere.
 */

/** How many fields a JSON contract declares; 0 when it declares none. */
export function contractFieldCount(contract: unknown): number {
  if (!contract || typeof contract !== "object") return 0;
  const properties = (contract as { properties?: unknown }).properties;
  return properties && typeof properties === "object" && !Array.isArray(properties)
    ? Object.keys(properties).length
    : 0;
}

/** What a step answers with, as a label: "Löpande text", "3 fasta fält". */
export function answerLabel(outputType: string | null | undefined, fieldCount: number): string {
  switch (outputType ?? "text") {
    case "json":
      if (fieldCount === 1) return m.ai_builder_answer_fields_one();
      return fieldCount > 1
        ? m.ai_builder_answer_fields({ count: String(fieldCount) })
        : m.ai_builder_answer_structured();
    case "pdf":
      return m.ai_builder_answer_pdf();
    case "docx":
      return m.ai_builder_answer_docx();
    default:
      return m.ai_builder_answer_text();
  }
}

/** The same answer inside a sentence: "löpande text", "ett PDF-dokument". */
export function answerPhrase(outputType: string | null | undefined, fieldCount: number): string {
  switch (outputType ?? "text") {
    case "json":
      if (fieldCount === 1) return m.ai_builder_answer_fields_one_phrase();
      return fieldCount > 1
        ? m.ai_builder_answer_fields_phrase({ count: String(fieldCount) })
        : m.ai_builder_answer_structured_phrase();
    case "pdf":
      return m.ai_builder_answer_pdf_phrase();
    case "docx":
      return m.ai_builder_answer_docx_phrase();
    default:
      return m.ai_builder_answer_text_phrase();
  }
}

function stepsLabel(orders: number[]): string {
  const sorted = [...new Set(orders)].sort((a, b) => a - b);
  if (sorted.length === 1) return m.ai_builder_reads_step({ step: String(sorted[0]) });
  if (sorted.length === 2) {
    return m.ai_builder_reads_steps_two({ first: String(sorted[0]), second: String(sorted[1]) });
  }
  const contiguous = sorted.every((order, index) => index === 0 || order === sorted[index - 1] + 1);
  if (contiguous) {
    return m.ai_builder_reads_steps_range({
      first: String(sorted[0]),
      last: String(sorted[sorted.length - 1])
    });
  }
  return m.ai_builder_reads_steps_listed({ steps: sorted.join(", ") });
}

/**
 * What a planned step reads, as a label ("Föregående steg", "Steg 1 och 2").
 * `stepNumber` is the step's 1-based position; `stepNumberOf` resolves a plan
 * step reference named in the step's material to its position.
 *
 * Explicit underlag (chosen results or its own text) replaces the step's input
 * source at run time, so it is read first: the steps and the flow input its
 * references name, or "Egen text" when it names neither.
 */
export function readsLabel(
  step: Pick<StepSpec, "input_source" | "input_bindings">,
  stepNumber: number,
  stepNumberOf: (planStepRef: string) => number | null
): string {
  const bindings = parseFlowInputBindings(step.input_bindings);
  const question = bindings.status === "valid" ? (bindings.question?.trim() ?? "") : "";
  if (bindings.status === "valid" && (bindings.sourceRefs.length > 0 || question)) {
    const tokenRefs = extractTemplateTokens(question).map((token) => token.split(".")[0].trim());
    const orders = [...bindings.sourceRefs.map((source) => source.stepRef), ...tokenRefs]
      .map((ref) => stepNumberOf(ref))
      .filter((order): order is number => order !== null && order < stepNumber);
    const parts = [
      ...(tokenRefs.includes("flow_input") ? [m.ai_builder_reads_flow_input()] : []),
      ...(orders.length > 0 ? [stepsLabel(orders)] : [])
    ];
    if (parts.length > 0) {
      const locale = getLocale();
      return new Intl.ListFormat(locale, { type: "conjunction" }).format(
        parts.map((part, index) => (index === 0 ? part : inSentence(part, locale)))
      );
    }
    // Text of its own is what the step reads; a reference that names no
    // earlier step says nothing, so the input source stands.
    if (question.replace(new RegExp(TEMPLATE_TOKEN_PATTERN_SOURCE, "g"), "").trim()) {
      return m.ai_builder_reads_own_text();
    }
  }
  if (step.input_source === "previous_step" && stepNumber > 1) return m.ai_builder_reads_previous();
  if (step.input_source === "all_previous_steps" && stepNumber > 1) {
    return stepsLabel(Array.from({ length: stepNumber - 1 }, (_, index) => index + 1));
  }
  return m.ai_builder_reads_flow_input();
}

/** A label inside a sentence: the first letter lowered unless it opens an acronym. */
export function inSentence(label: string, locale: string): string {
  if (/^\p{Lu}{2}/u.test(label)) return label;
  return label.charAt(0).toLocaleLowerCase(locale) + label.slice(1);
}

export type ContractField = { type?: string; title?: string; description?: string };
type Contract = { properties?: unknown; required?: unknown } | null | undefined;

/**
 * A contract's fields in the order its required list names them: the schema's
 * object keys arrive sorted, the required list keeps the order they were asked
 * for in.
 */
export function contractFields(contract: Contract): [string, ContractField][] {
  const properties = contract?.properties;
  if (!properties || typeof properties !== "object" || Array.isArray(properties)) return [];
  const required = Array.isArray(contract?.required) ? (contract.required as unknown[]) : [];
  const rank = (key: string) => {
    const index = required.indexOf(key);
    return index === -1 ? required.length : index;
  };
  return Object.entries(properties as Record<string, ContractField>).sort(
    ([a], [b]) => rank(a) - rank(b)
  );
}

function fold(text: string, locale: string): string {
  return text.normalize("NFD").replace(/\p{M}/gu, "").toLocaleLowerCase(locale);
}

// A name written in plain ASCII ("riskniva") takes the spelling its
// description uses for the same words ("Bedömd risknivå").
function spelledAsIn(words: string, description: string | undefined, locale: string): string {
  if (!description || !/^[\x20-\x7e]*$/.test(words)) return words;
  const target = fold(words, locale);
  const tokens = description.split(/[^\p{L}\p{N}]+/u).filter(Boolean);
  const size = words.split(" ").length;
  for (let start = 0; start + size <= tokens.length; start++) {
    const candidate = tokens.slice(start, start + size).join(" ");
    if (fold(candidate, locale) === target) return candidate;
  }
  return words;
}

/** A field's readable name: its title, or its snake_case key unwrapped. */
export function fieldLabel(key: string, field: ContractField, locale: string): string {
  const name = field.title?.trim() || key.replace(/[_-]+/g, " ").trim();
  const spelled = spelledAsIn(name, field.description, locale);
  return spelled.charAt(0).toLocaleUpperCase(locale) + spelled.slice(1);
}

/** A field's description, unless it only repeats the name. */
export function fieldDescription(
  label: string,
  field: ContractField,
  locale: string
): string | null {
  const description = field.description?.trim();
  if (!description) return null;
  return fold(description.replace(/[.\s]+$/, ""), locale) === fold(label, locale)
    ? null
    : description;
}
