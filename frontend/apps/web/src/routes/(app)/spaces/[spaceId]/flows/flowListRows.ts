import type { FlowSparse } from "@eneo/eneo-js";
import { m } from "$lib/paraglide/messages";
import type { RecoverableAIBuilderDraftSession } from "$lib/features/flows/ai-builder/protocol";

/** One row in the Flöden list: a saved flow or an in-progress AI draft.
 *  Both kinds sort and filter together — a draft is where a flow starts. */
export type FlowListRow =
  | {
      kind: "flow";
      id: string;
      name: string;
      subtitle: string | null;
      status: "published" | "draft";
      ownerUserId: string | null;
      updatedAt: string | null;
      flow: FlowSparse;
    }
  | {
      kind: "ai_draft";
      id: string;
      name: string | null;
      subtitle: string | null;
      status: "draft";
      /** Same three phases as the builder rail; the list can only see two of them. */
      phase: "understanding" | "reviewing";
      ownerUserId: null;
      updatedAt: string | null;
      draft: RecoverableAIBuilderDraftSession;
    };

export type FlowListFilter = "all" | "published" | "drafts";

/** "5 steg · ljud in, PDF ut": what the flow is, in one line, for a reader who
 *  has not opened it. A flow with no steps has nothing to summarise, so its
 *  description speaks instead; a flow whose input or output the server cannot
 *  name says the part it knows. */
function describeFlow(flow: FlowSparse): string | null {
  const stepCount = flow.step_count;
  if (stepCount === 0) return flow.description?.trim() || null;

  const steps =
    stepCount === 1
      ? m.flow_list_row_steps_one()
      : m.flow_list_row_steps({ count: String(stepCount) });
  const input = flow.input_type ? FLOW_INPUT_LABELS[flow.input_type]() : null;
  const output = flow.output_type ? FLOW_OUTPUT_LABELS[flow.output_type]() : null;
  const shape =
    input && output ? m.flow_list_row_shape({ input, output }) : (input ?? output ?? null);
  return shape ? `${steps} · ${shape}` : steps;
}

const FLOW_INPUT_LABELS: Record<NonNullable<FlowSparse["input_type"]>, () => string> = {
  document: () => m.flow_list_input_document(),
  audio: () => m.flow_list_input_audio(),
  file: () => m.flow_list_input_file()
};

const FLOW_OUTPUT_LABELS: Record<NonNullable<FlowSparse["output_type"]>, () => string> = {
  text: () => m.flow_list_output_text(),
  json: () => m.flow_list_output_json(),
  pdf: () => m.flow_list_output_pdf(),
  docx: () => m.flow_list_output_docx()
};

export function buildFlowListRows(
  flows: readonly FlowSparse[],
  drafts: readonly RecoverableAIBuilderDraftSession[]
): FlowListRow[] {
  const flowRows: FlowListRow[] = flows.map((flow) => ({
    kind: "flow",
    id: flow.id,
    name: flow.name,
    subtitle: describeFlow(flow),
    status: flow.published_version != null ? "published" : "draft",
    ownerUserId: flow.owner_user_id ?? flow.created_by_user_id ?? null,
    updatedAt: flow.updated_at ?? flow.created_at ?? null,
    flow
  }));
  const draftRows: FlowListRow[] = drafts.map((draft) => ({
    kind: "ai_draft",
    id: draft.session_id,
    name: draft.draft_title?.trim() || null,
    subtitle: null,
    status: "draft",
    phase: draft.status === "awaiting_approval" ? "reviewing" : "understanding",
    ownerUserId: null,
    updatedAt: draft.updated_at ?? draft.created_at ?? null,
    draft
  }));
  return [...flowRows, ...draftRows].sort(
    (a, b) => timestamp(b.updatedAt) - timestamp(a.updatedAt)
  );
}

function timestamp(value: string | null): number {
  if (!value) return 0;
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? 0 : parsed;
}

export function filterFlowListRows(
  rows: readonly FlowListRow[],
  options: { query: string; filter: FlowListFilter }
): FlowListRow[] {
  const query = options.query.trim().toLocaleLowerCase();
  return rows.filter((row) => {
    if (options.filter === "published" && row.status !== "published") return false;
    if (options.filter === "drafts" && row.status !== "draft") return false;
    if (!query) return true;
    // The row may show a derived summary instead of the description, but the
    // description is still what people remember a flow by.
    const description = row.kind === "flow" ? (row.flow.description ?? "") : "";
    const haystack = `${row.name ?? ""} ${row.subtitle ?? ""} ${description}`.toLocaleLowerCase();
    return haystack.includes(query);
  });
}

export type FlowListUpdatedLabel =
  | { kind: "today"; time: string }
  | { kind: "yesterday"; time: string }
  | { kind: "days_ago"; days: number }
  | { kind: "date"; date: string }
  | { kind: "unknown" };

/** Relative wording inside a week, an absolute date after; the full
 *  timestamp belongs in the tooltip, not the cell. */
export function describeUpdatedAt(
  value: string | null,
  now: Date,
  locale: string
): FlowListUpdatedLabel {
  if (!value) return { kind: "unknown" };
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return { kind: "unknown" };
  const time = date.toLocaleTimeString(locale, { hour: "2-digit", minute: "2-digit" });
  const startOfDay = (d: Date) => new Date(d.getFullYear(), d.getMonth(), d.getDate()).getTime();
  const dayDiff = Math.round((startOfDay(now) - startOfDay(date)) / 86_400_000);
  if (dayDiff <= 0) return { kind: "today", time };
  if (dayDiff === 1) return { kind: "yesterday", time };
  if (dayDiff < 7) return { kind: "days_ago", days: dayDiff };
  return { kind: "date", date: date.toLocaleDateString(locale) };
}
