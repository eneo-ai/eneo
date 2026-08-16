import { describe, expect, it } from "vitest";
import type { FlowSparse } from "@eneo/eneo-js";
import type { RecoverableAIBuilderDraftSession } from "$lib/features/flows/ai-builder/protocol";
import { buildFlowListRows, describeUpdatedAt, filterFlowListRows } from "./flowListRows";

function flow(overrides: Partial<FlowSparse>): FlowSparse {
  return {
    id: "flow-1",
    name: "Ljud till PDF",
    space_id: "space-1",
    tenant_id: "tenant-1",
    run_history_retention: { state: "off" },
    ...overrides
  } as FlowSparse;
}

function draft(
  overrides: Partial<RecoverableAIBuilderDraftSession>
): RecoverableAIBuilderDraftSession {
  return {
    session_id: "draft-1",
    space_id: "space-1",
    status: "chatting",
    target_kind: "create",
    flow_id: null,
    latest_plan_id: null,
    draft_title: "Transkribering av nämndmöten",
    created_at: "2026-08-15T16:20:00Z",
    updated_at: "2026-08-15T16:20:00Z",
    ...overrides
  } as RecoverableAIBuilderDraftSession;
}

describe("buildFlowListRows", () => {
  it("merges flows and AI drafts into one list sorted by last change", () => {
    const rows = buildFlowListRows(
      [
        flow({
          id: "old",
          name: "Gammal",
          published_version: 2,
          updated_at: "2026-08-04T13:40:00Z"
        }),
        flow({ id: "new", name: "Ny", updated_at: "2026-08-16T09:52:00Z" })
      ],
      [draft({ updated_at: "2026-08-16T09:41:00Z", status: "awaiting_approval" })]
    );

    expect(rows.map((row) => row.id)).toEqual(["new", "draft-1", "old"]);
    expect(rows[0]).toMatchObject({ kind: "flow", status: "draft" });
    expect(rows[1]).toMatchObject({ kind: "ai_draft", status: "draft", phase: "reviewing" });
    expect(rows[2]).toMatchObject({ kind: "flow", status: "published" });
  });

  it("keeps an untitled draft resumable instead of hiding it", () => {
    const [row] = buildFlowListRows([], [draft({ draft_title: null })]);
    expect(row).toMatchObject({ kind: "ai_draft", name: null, phase: "understanding" });
  });
});

describe("filterFlowListRows", () => {
  const rows = buildFlowListRows(
    [
      flow({
        id: "p",
        name: "Publicerat flöde",
        published_version: 1,
        updated_at: "2026-08-16T09:00:00Z"
      }),
      flow({
        id: "d",
        name: "Utkastflöde",
        description: "Läs remissvaren",
        updated_at: "2026-08-16T08:00:00Z"
      })
    ],
    [draft({ draft_title: "Sammanställ remissvar", updated_at: "2026-08-15T16:20:00Z" })]
  );

  it("filters drafts and published rows separately", () => {
    expect(filterFlowListRows(rows, { query: "", filter: "published" }).map((r) => r.id)).toEqual([
      "p"
    ]);
    expect(filterFlowListRows(rows, { query: "", filter: "drafts" }).map((r) => r.id)).toEqual([
      "d",
      "draft-1"
    ]);
  });

  it("matches the query against name and description regardless of case", () => {
    expect(filterFlowListRows(rows, { query: "REMISS", filter: "all" }).map((r) => r.id)).toEqual([
      "d",
      "draft-1"
    ]);
    expect(filterFlowListRows(rows, { query: "finns inte", filter: "all" })).toEqual([]);
  });
});

describe("describeUpdatedAt", () => {
  const now = new Date(2026, 7, 16, 12, 0);

  it("uses relative wording inside a week and a date after", () => {
    expect(describeUpdatedAt("2026-08-16T07:52:00Z", now, "sv").kind).toBe("today");
    expect(describeUpdatedAt("2026-08-15T14:20:00Z", now, "sv").kind).toBe("yesterday");
    expect(describeUpdatedAt("2026-08-12T10:00:00Z", now, "sv")).toMatchObject({
      kind: "days_ago",
      days: 4
    });
    expect(describeUpdatedAt("2026-08-04T10:00:00Z", now, "sv").kind).toBe("date");
    expect(describeUpdatedAt(null, now, "sv").kind).toBe("unknown");
    expect(describeUpdatedAt("not a date", now, "sv").kind).toBe("unknown");
  });
});
