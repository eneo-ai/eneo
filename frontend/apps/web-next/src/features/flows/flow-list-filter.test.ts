import { describe, expect, it } from "vitest";
import type { FlowSparse } from "./flows-api";
import { flowChangedAt, flowOwner, matchingFlows } from "./flow-list-filter";

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

const ids = (flows: FlowSparse[]) => flows.map((item) => item.id);

describe("flowChangedAt", () => {
  it("dates a flow by its last change, a never changed one by its creation and one without dates as 0", () => {
    expect(
      flowChangedAt(
        flow({ updated_at: "2026-08-16T09:52:00Z", created_at: "2026-01-01T00:00:00Z" })
      )
    ).toBe(Date.parse("2026-08-16T09:52:00Z"));
    expect(flowChangedAt(flow({ created_at: "2026-08-10T09:00:00Z" }))).toBe(
      Date.parse("2026-08-10T09:00:00Z")
    );
    expect(flowChangedAt(flow({}))).toBe(0);
    expect(flowChangedAt(flow({ updated_at: "not a date" }))).toBe(0);
  });
});

describe("matchingFlows", () => {
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
    expect(ids(matchingFlows(flows, "REMISS", subtitle))).toEqual(["letter"]);
    expect(ids(matchingFlows(flows, "ljud", subtitle))).toEqual(["audio"]);
    expect(ids(matchingFlows(flows, "  medborgar  ", subtitle))).toEqual(["letter"]);
    expect(matchingFlows(flows, "finns inte", subtitle)).toEqual([]);
    // An empty query keeps every flow, in the order given.
    expect(ids(matchingFlows(flows, "   ", subtitle))).toEqual(["letter", "audio"]);
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
