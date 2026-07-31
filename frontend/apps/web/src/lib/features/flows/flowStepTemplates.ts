import type { FlowStep } from "@eneo/eneo-js";
import type { FlowStepCreationSeed } from "./FlowEditor";
import { m } from "$lib/paraglide/messages";
import AlignLeft from "lucide-svelte/icons/align-left";
import PencilLine from "lucide-svelte/icons/pencil-line";
import Table from "lucide-svelte/icons/table";
import Tags from "lucide-svelte/icons/tags";
import WrapText from "lucide-svelte/icons/wrap-text";
import FileText from "lucide-svelte/icons/file-text";
import Plus from "lucide-svelte/icons/plus";

/** A lucide-svelte icon component; every icon shares this shape. */
type LucideIcon = typeof AlignLeft;

/**
 * A pre-authored starting point for a new flow step: a name, a starter
 * instruction, and the output shape it produces. Templates set only the output
 * side and the instruction — the input side is derived from the step's position
 * so a template stays valid wherever it is added.
 */
export interface FlowStepTemplate {
  id: string;
  name: () => string;
  description: () => string;
  /** Extra search terms so the template surfaces for related queries. */
  aliases?: readonly string[];
  icon: LucideIcon;
  /** Input type for the "input → output" hint the picker renders. */
  displayInputType: FlowStep["input_type"];
  outputType: FlowStep["output_type"];
  outputMode: "pass_through";
  prompt?: () => string;
  /** Only offered as recommended when the previous step outputs JSON. */
  requiresJsonInput?: boolean;
  /** The blank fallback — creates a default step with no overrides. */
  blank?: boolean;
}

export const FLOW_STEP_TEMPLATES: readonly FlowStepTemplate[] = [
  {
    id: "summarize",
    name: () => m.flow_template_summarize_name(),
    description: () => m.flow_template_summarize_desc(),
    icon: AlignLeft,
    displayInputType: "text",
    outputType: "text",
    outputMode: "pass_through",
    prompt: () => m.flow_template_summarize_prompt()
  },
  {
    id: "review",
    name: () => m.flow_template_review_name(),
    description: () => m.flow_template_review_desc(),
    icon: PencilLine,
    displayInputType: "text",
    outputType: "text",
    outputMode: "pass_through",
    prompt: () => m.flow_template_review_prompt()
  },
  {
    id: "extract",
    name: () => m.flow_template_extract_name(),
    description: () => m.flow_template_extract_desc(),
    icon: Table,
    displayInputType: "text",
    outputType: "json",
    outputMode: "pass_through",
    prompt: () => m.flow_template_extract_prompt()
  },
  {
    id: "classify",
    name: () => m.flow_template_classify_name(),
    description: () => m.flow_template_classify_desc(),
    icon: Tags,
    displayInputType: "text",
    outputType: "text",
    outputMode: "pass_through",
    prompt: () => m.flow_template_classify_prompt()
  },
  {
    id: "render_text",
    name: () => m.flow_template_render_text_name(),
    description: () => m.flow_template_render_text_desc(),
    icon: WrapText,
    displayInputType: "json",
    outputType: "text",
    outputMode: "pass_through",
    prompt: () => m.flow_template_render_text_prompt(),
    requiresJsonInput: true
  },
  {
    id: "document",
    name: () => m.flow_template_document_name(),
    description: () => m.flow_template_document_desc(),
    aliases: ["pdf", "word", "docx", "dokument", "document", "rapport", "report", "export"],
    icon: FileText,
    displayInputType: "text",
    outputType: "docx",
    outputMode: "pass_through",
    prompt: () => m.flow_template_document_prompt()
  },
  {
    id: "blank",
    name: () => m.flow_template_blank_name(),
    description: () => m.flow_template_blank_desc(),
    icon: Plus,
    displayInputType: "text",
    outputType: "text",
    outputMode: "pass_through",
    blank: true
  }
];

/**
 * Maps a configured template to the seed `FlowEditor.addStep` accepts. Returns
 * null for the blank template so a blank selection can never be turned into a
 * seeded, named step — the caller falls back to `addStep()`.
 */
export function templateToAddStepOptions(template: FlowStepTemplate): FlowStepCreationSeed | null {
  if (template.blank) return null;
  return {
    name: template.name(),
    output_type: template.outputType,
    output_mode: template.outputMode,
    prompt: template.prompt?.()
  };
}

/**
 * Split the catalog into what to recommend after a step producing
 * `prevOutputType` (null for the first step, treated as text). Templates that
 * need JSON input, plus the blank fallback, drop to "more".
 */
export function getRecommendedTemplates(prevOutputType: FlowStep["output_type"] | null): {
  recommended: FlowStepTemplate[];
  more: FlowStepTemplate[];
} {
  const recommended: FlowStepTemplate[] = [];
  const more: FlowStepTemplate[] = [];
  for (const template of FLOW_STEP_TEMPLATES) {
    if (template.blank) {
      more.push(template);
    } else if (template.requiresJsonInput && prevOutputType !== "json") {
      more.push(template);
    } else {
      recommended.push(template);
    }
  }
  return { recommended, more };
}

/** Case-insensitive filter over template name + description. */
export function filterTemplates(
  templates: readonly FlowStepTemplate[],
  query: string
): FlowStepTemplate[] {
  const q = query.trim().toLowerCase();
  if (!q) return [...templates];
  return templates.filter(
    (t) =>
      t.name().toLowerCase().includes(q) ||
      t.description().toLowerCase().includes(q) ||
      (t.aliases?.some((alias) => alias.toLowerCase().includes(q)) ?? false)
  );
}

/**
 * Resolve a template plus the chosen document format into an add-step seed. The
 * document template can produce Word (docx) or PDF — both are pass_through
 * document renderers, no extra config. Other templates ignore the format.
 */
export function resolveTemplateSeed(
  template: FlowStepTemplate,
  documentFormat: "docx" | "pdf"
): FlowStepCreationSeed | null {
  const seed = templateToAddStepOptions(template);
  if (seed && template.id === "document") {
    return {
      ...seed,
      name:
        documentFormat === "pdf"
          ? m.flow_template_document_name_pdf()
          : m.flow_template_document_name_word(),
      output_type: documentFormat
    };
  }
  return seed;
}
