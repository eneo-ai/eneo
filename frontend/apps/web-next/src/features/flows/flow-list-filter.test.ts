import { describe, expect, it } from "vitest";
import type { FlowSparse } from "./flows-api";
import { flowChangedAt, flowOwner, visibleFlows } from "./flow-list-filter";

function flow(overrides: Partial<FlowSparse>): FlowSparse {
  return {
    id: "flow-1",
    name: "Ljud till PDF",
    description: null,
    published_version: null,
    updated_at: null,
    created_at: null,
    ...overrides
  } as FlowSparse;
}

const all = { query: "", status: "all" } as const;
const noSubtitle = () => null;
const ids = (flows: FlowSparse[]) => flows.map((item) => item.id);

describe("visibleFlows", () => {
  it("shows the last changed flow first, a never changed one by its creation and one without dates last", () => {
    const flows = [
      flow({ id: "undated" }),
      flow({ id: "old", updated_at: "2026-08-04T13:40:00Z" }),
      flow({ id: "created", created_at: "2026-08-10T09:00:00Z" }),
      flow({ id: "new", updated_at: "2026-08-16T09:52:00Z", created_at: "2026-01-01T00:00:00Z" }),
      flow({ id: "garbled", updated_at: "not a date" })
    ];
    expect(ids(visibleFlows(flows, all, noSubtitle))).toEqual([
      "new",
      "created",
      "old",
      "undated",
      "garbled"
    ]);
    // The list it was given keeps its order.
    expect(flows[0]?.id).toBe("undated");
    expect(flowChangedAt(flow({ updated_at: "not a date" }))).toBe(0);
  });

  it("keeps a flow findable by its description and by what it takes in and gives back, in any case", () => {
    const flows = [
      flow({
        id: "letter",
        name: "Medborgarbrev",
        description: "Sammanställ remissvar per avsnitt"
      }),
      flow({ id: "audio", name: "Mötesprotokoll", input_type: "audio" })
    ];
    const subtitle = (item: FlowSparse) => (item.input_type === "audio" ? "Indata: Ljud" : null);
    expect(ids(visibleFlows(flows, { query: "REMISS", status: "all" }, subtitle))).toEqual([
      "letter"
    ]);
    expect(ids(visibleFlows(flows, { query: "ljud", status: "all" }, subtitle))).toEqual(["audio"]);
    expect(ids(visibleFlows(flows, { query: "  medborgar  ", status: "all" }, subtitle))).toEqual([
      "letter"
    ]);
    expect(visibleFlows(flows, { query: "finns inte", status: "all" }, subtitle)).toEqual([]);
    expect(visibleFlows(flows, { query: "   ", status: "all" }, subtitle)).toHaveLength(2);
  });

  it("filters published flows and drafts separately, then by the query", () => {
    const flows = [
      flow({ id: "published", name: "Publicerat flöde", published_version: 1 }),
      flow({ id: "draft", name: "Utkastflöde", description: "Läs remissvaren" }),
      flow({ id: "first", name: "Första versionen", published_version: 0 })
    ];
    expect(ids(visibleFlows(flows, { query: "", status: "published" }, noSubtitle))).toEqual([
      "published",
      "first"
    ]);
    expect(ids(visibleFlows(flows, { query: "", status: "drafts" }, noSubtitle))).toEqual([
      "draft"
    ]);
    expect(visibleFlows(flows, { query: "remiss", status: "published" }, noSubtitle)).toEqual([]);
  });
});

describe("flowOwner", () => {
  const members = [
    { id: "user-2", username: "anna.lind", email: "anna.lind@kommun.se" },
    { id: "user-3", username: null, email: "per@kommun.se" }
  ];

  it("says the viewer, a member by name or e-mail, someone outside the space, or nobody", () => {
    expect(flowOwner(flow({ owner_user_id: "user-1" }), "user-1", members)).toEqual({
      kind: "you"
    });
    // A flow nobody took over belongs to the one who created it.
    expect(flowOwner(flow({ created_by_user_id: "user-2" }), "user-1", members)).toEqual({
      kind: "member",
      name: "anna.lind"
    });
    expect(
      flowOwner(flow({ owner_user_id: "user-3", created_by_user_id: "user-1" }), "user-1", members)
    ).toEqual({ kind: "member", name: "per@kommun.se" });
    expect(flowOwner(flow({ owner_user_id: "user-9" }), "user-1", members)).toEqual({
      kind: "unknown"
    });
    expect(flowOwner(flow({}), "user-1", members)).toBeNull();
  });
});
