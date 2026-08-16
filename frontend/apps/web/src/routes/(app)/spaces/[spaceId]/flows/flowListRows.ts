import type { FlowSparse } from "@eneo/eneo-js";
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

export function buildFlowListRows(
  flows: readonly FlowSparse[],
  drafts: readonly RecoverableAIBuilderDraftSession[]
): FlowListRow[] {
  const flowRows: FlowListRow[] = flows.map((flow) => ({
    kind: "flow",
    id: flow.id,
    name: flow.name,
    subtitle: flow.description?.trim() || null,
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
    const haystack = `${row.name ?? ""} ${row.subtitle ?? ""}`.toLocaleLowerCase();
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
