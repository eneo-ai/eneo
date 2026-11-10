import {
  AlignLeft,
  AudioLines,
  Combine,
  Download,
  FileInput,
  FileText,
  PencilLine,
  Plus,
  Send,
  Table,
  Tags,
  UserCheck,
  Users,
  Wrench,
  WrapText,
  type LucideIcon
} from "lucide-react";
import type { DocumentFormat, StepKind, StepKindOption } from "./step-kinds";
import type { OutputType } from "./step-types";

/**
 * What the add dialog offers: tasks a person recognises ("Sammanfatta"), each
 * one of the core's kinds with a starter instruction, then the kinds that are
 * a task of their own. The tasks are those of the Svelte step picker
 * (`flowStepTemplates.ts`). Every row reads `flow_add_step_<id>` and
 * `flow_add_step_<id>_description`.
 */
export type StepTask = {
  id: string;
  kind: StepKind;
  icon: LucideIcon;
  /** Catalog key of the instruction the step's AI starts with. */
  prompt?: string;
  /** Catalog key of the new step's name, where `taskStepName` would not give the right one. */
  stepName?: string;
  /** Words people search for beyond the name and the description. */
  aliases: string;
  /** Offered only where its kind reads JSON: after a step that answers in a fixed format. */
  readsJson?: true;
};

export const STEP_TASKS: readonly StepTask[] = [
  {
    id: "summarize",
    kind: "ai",
    icon: AlignLeft,
    prompt: "flow_template_summarize_prompt",
    aliases: "sammanfattning kortfattat referat summary"
  },
  {
    id: "improve",
    kind: "ai",
    icon: PencilLine,
    prompt: "flow_add_step_improve_prompt",
    aliases: "granska språk korrektur skriv om rewrite"
  },
  {
    id: "extract",
    kind: "structured",
    icon: Table,
    prompt: "flow_template_extract_prompt",
    aliases: "json fält fast format strukturerad extract"
  },
  {
    id: "classify",
    kind: "ai",
    icon: Tags,
    prompt: "flow_add_step_classify_prompt",
    aliases: "kategori kategorisera sortera bedöm classify"
  },
  {
    id: "render_text",
    kind: "ai",
    icon: WrapText,
    prompt: "flow_template_render_text_prompt",
    aliases: "json data fält löptext",
    readsJson: true
  },
  {
    id: "document",
    kind: "document",
    icon: FileText,
    aliases: "pdf word docx rapport export dokument"
  },
  {
    id: "template",
    kind: "template",
    icon: FileInput,
    aliases: "mall word docx protokoll tjänsteskrivelse dokument"
  },
  {
    id: "compose",
    kind: "compose",
    icon: Combine,
    aliases: "sätt ihop slå ihop mall utan ai"
  },
  {
    id: "transcribe",
    kind: "transcribe",
    icon: AudioLines,
    aliases: "ljud inspelning tal möte audio"
  },
  {
    id: "speakers",
    kind: "speakers",
    icon: Users,
    aliases: "talare vem säger transkript"
  },
  {
    id: "review",
    kind: "review",
    icon: UserCheck,
    aliases: "person godkänn rätta granska manuellt"
  },
  {
    id: "fetch_http",
    kind: "fetch_http",
    icon: Download,
    aliases: "api http get hämta webb adress url"
  },
  {
    id: "tool",
    kind: "tool",
    icon: Wrench,
    aliases: "mcp verktyg anropa"
  },
  {
    id: "send_http",
    kind: "send_http",
    icon: Send,
    aliases: "api http post webhook skicka ärendesystem"
  },
  {
    id: "blank",
    kind: "ai",
    icon: Plus,
    stepName: "flow_step_editor_kind_ai_name",
    aliases: "tomt eget ai"
  }
];

/**
 * Catalog key of the name a new step of `task` gets: a task with a starter
 * instruction is named after itself ("Sammanfatta"), a kind of its own keeps
 * the kind's step name ("Hämta data").
 */
export function taskStepName(task: StepTask): string {
  if (task.stepName) return task.stepName;
  return task.prompt ? `flow_add_step_${task.id}` : `flow_step_editor_kind_${task.kind}_name`;
}

/** The tasks recommended after a step that gives `previous` (null: the new step comes first). */
const RECOMMENDED: Record<"first" | "text" | "json", readonly string[]> = {
  first: ["summarize", "extract", "transcribe"],
  text: ["summarize", "improve", "extract", "classify", "document", "template"],
  json: ["render_text", "template", "send_http"]
};

export function recommendedTaskIds(previous: OutputType | null): readonly string[] {
  if (previous === null) return RECOMMENDED.first;
  if (previous === "text" || previous === "json") return RECOMMENDED[previous];
  return [];
}

/** Whether the task can stand where `option` is the core's answer for its kind. */
export function taskFits(task: StepTask, option: StepKindOption | null): boolean {
  if (!option) return false;
  return !task.readsJson || option.configuration.input_type === "json";
}

/**
 * Whether `query` finds the task: every word of it in the name, the
 * description or the aliases, ignoring case.
 */
export function taskMatches(task: StepTask, query: string, text: (key: string) => string) {
  const words = query.toLocaleLowerCase("sv").split(/\s+/).filter(Boolean);
  if (words.length === 0) return true;
  const haystack = [
    text(`flow_add_step_${task.id}`),
    text(`flow_add_step_${task.id}_description`),
    task.aliases
  ]
    .join(" ")
    .toLocaleLowerCase("sv");
  return words.every((word) => haystack.includes(word));
}

/** The document format a search asks for: PDF when it names it, else Word. */
export function searchedFormat(query: string): DocumentFormat {
  return /\bpdf\b/i.test(query) ? "pdf" : "docx";
}

/**
 * The short "in → out" of a step the core would start with `configuration`,
 * as the step card reads after adding: where it reads from and what it gives.
 */
export function taskFlow(
  option: StepKindOption,
  format: DocumentFormat,
  text: (key: string) => string
): { from: string; to: string } {
  const { input_source: source, input_type: input, output_mode: mode } = option.configuration;
  const from = source === "http_get" ? "http" : source === "tool" ? "tool" : input;
  const to =
    mode === "http_post"
      ? "http"
      : option.kind === "document"
        ? format
        : option.configuration.output_type;
  return { from: text(`flow_add_step_io_${from}`), to: text(`flow_add_step_io_${to}`) };
}
