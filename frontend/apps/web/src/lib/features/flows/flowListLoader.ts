import type { Eneo, FlowSparse } from "@eneo/eneo-js";

export class FlowListPaginationError extends Error {
  constructor() {
    super("The flow list did not provide a progressing page.");
    this.name = "FlowListPaginationError";
  }
}

export async function loadFlowList(eneo: Eneo, spaceId: string): Promise<FlowSparse[]> {
  const flows: FlowSparse[] = [];
  const ids = new Set<string>();
  let offset = 0;
  while (true) {
    // The server accepts at most 200 per page; count describes this page, not the total.
    const page = await eneo.flows.list({ spaceId, limit: 200, offset });
    if (
      !Array.isArray(page.items) ||
      typeof page.has_more !== "boolean" ||
      (page.has_more && page.items.length === 0)
    ) {
      throw new FlowListPaginationError();
    }
    for (const flow of page.items) {
      if (ids.has(flow.id)) throw new FlowListPaginationError();
      ids.add(flow.id);
      flows.push(flow);
    }
    if (!page.has_more) return flows;
    offset += page.items.length;
  }
}
