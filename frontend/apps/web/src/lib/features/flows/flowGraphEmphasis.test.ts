import { describe, it, expect } from "vitest";
import {
  computeFlowExportSize,
  computeFlowGraphEmphasis,
  emptyFlowGraphPreviewState,
  reduceFlowGraphPreview,
  resolveFlowGraphPreviewId,
  type FlowGraphEmphasisEdge,
  type FlowGraphPreviewEvent
} from "./flowStepPresentation";

/**
 * The shape this flow actually has: a chain that fans out to parallel-looking
 * steps and converges again. They are not parallel -- the runtime executes in
 * step order -- but the edges say what feeds what, and that is what the graph
 * may claim.
 */
const edges: FlowGraphEmphasisEdge[] = [
  { id: "e-in-1", source: "input", target: "s1" },
  { id: "e-1-2", source: "s1", target: "s2" },
  { id: "e-2-3", source: "s2", target: "s3" },
  { id: "e-3-4", source: "s3", target: "s4" },
  { id: "e-3-5", source: "s3", target: "s5" },
  { id: "e-4-6", source: "s4", target: "s6" },
  { id: "e-5-6", source: "s5", target: "s6" },
  { id: "e-6-out", source: "s6", target: "output" }
];

describe("computeFlowGraphEmphasis", () => {
  it("emphasises nothing when no step is selected or pointed at", () => {
    const emphasis = computeFlowGraphEmphasis({ edges, activeId: null, previewId: null });

    expect(emphasis.hasFocus).toBe(false);
    expect(emphasis.isPreview).toBe(false);
    expect(Object.keys(emphasis.litNodes)).toEqual([]);
  });

  /**
   * Pointing at a step asks "what feeds this one". One hop back, because a
   * transitive answer here would bury the underlag being configured.
   */
  it("lights only the direct underlag of the step being pointed at", () => {
    const emphasis = computeFlowGraphEmphasis({ edges, activeId: "s1", previewId: "s6" });

    expect(Object.keys(emphasis.litNodes).sort()).toEqual(["s4", "s5", "s6"]);
    expect(Object.keys(emphasis.litEdges).sort()).toEqual(["e-4-6", "e-5-6"]);
    expect(emphasis.isPreview).toBe(true);
  });

  /**
   * Selecting a step asks "where does this sit in the flow" -- the whole path
   * it lies on, to both ends, so the answer reaches the input and the output.
   */
  it("traces the whole path through a selected step, both directions", () => {
    const emphasis = computeFlowGraphEmphasis({ edges, activeId: "s4", previewId: null });

    expect(Object.keys(emphasis.litNodes).sort()).toEqual([
      "input",
      "output",
      "s1",
      "s2",
      "s3",
      "s4",
      "s6"
    ]);
    // s5 is a sibling on the fan, not on this step's path.
    expect(emphasis.litNodes.s5).toBeUndefined();
    expect(emphasis.litEdges["e-3-5"]).toBeUndefined();
    expect(emphasis.litEdges["e-5-6"]).toBeUndefined();
  });

  it("reaches the ends of a long chain rather than stopping at a neighbour", () => {
    const emphasis = computeFlowGraphEmphasis({ edges, activeId: "s1", previewId: null });

    expect(emphasis.litNodes.input).toBe(true);
    expect(emphasis.litNodes.output).toBe(true);
    expect(emphasis.litNodes.s5).toBe(true);
  });

  /**
   * Pointing somewhere while a step is selected answers the pointed-at
   * question, so the reader can look around without losing their place.
   */
  it("lets a preview take over from the selection while it lasts", () => {
    const selected = computeFlowGraphEmphasis({ edges, activeId: "s4", previewId: null });
    const previewing = computeFlowGraphEmphasis({ edges, activeId: "s4", previewId: "s2" });

    expect(selected.litNodes.output).toBe(true);
    expect(previewing.litNodes.output).toBeUndefined();
    expect(Object.keys(previewing.litNodes).sort()).toEqual(["s1", "s2"]);
  });

  /**
   * isPreview is what gates the travelling dot. A selection persists, and a
   * persistent selection must not leave animations running at rest.
   */
  it("marks a selection as not a preview, so nothing animates at rest", () => {
    expect(computeFlowGraphEmphasis({ edges, activeId: "s4", previewId: null }).isPreview).toBe(
      false
    );
    expect(computeFlowGraphEmphasis({ edges, activeId: null, previewId: "s4" }).isPreview).toBe(
      true
    );
  });

  it("terminates on a cycle instead of walking it forever", () => {
    const looped: FlowGraphEmphasisEdge[] = [
      { id: "a", source: "x", target: "y" },
      { id: "b", source: "y", target: "x" }
    ];

    const emphasis = computeFlowGraphEmphasis({ edges: looped, activeId: "x", previewId: null });

    expect(Object.keys(emphasis.litNodes).sort()).toEqual(["x", "y"]);
  });
});

describe("computeFlowExportSize", () => {
  it("renders a small flow at twice its natural size", () => {
    const size = computeFlowExportSize({ width: 800, height: 400 });

    expect(size).not.toBeNull();
    expect(size?.scale).toBe(2);
    expect(size?.width).toBe((800 + 64) * 2);
    expect(size?.height).toBe((400 + 64) * 2);
  });

  /** A ceiling the result may exceed is not a ceiling. */
  it("stays inside the pixel budget for a graph too large to double", () => {
    const size = computeFlowExportSize({ width: 6000, height: 2400 });

    expect(size).not.toBeNull();
    expect(size!.width * size!.height).toBeLessThanOrEqual(16_000_000);
    expect(size!.scale).toBeLessThan(2);
  });

  it("stays inside the longest-edge budget for a long thin graph", () => {
    const size = computeFlowExportSize({ width: 40_000, height: 300 });

    expect(size).not.toBeNull();
    expect(Math.max(size!.width, size!.height)).toBeLessThanOrEqual(8192);
    expect(size!.width * size!.height).toBeLessThanOrEqual(16_000_000);
  });

  it("declines a graph with no extent rather than dividing by zero", () => {
    expect(computeFlowExportSize({ width: 0, height: 0 })).toBeNull();
    expect(computeFlowExportSize({ width: 100, height: 0 })).toBeNull();
  });
});

/** Plays a sequence of gestures and reports what is previewed at the end. */
function previewAfter(...events: FlowGraphPreviewEvent[]): string | null {
  return resolveFlowGraphPreviewId(
    events.reduce(reduceFlowGraphPreview, emptyFlowGraphPreviewState())
  );
}

describe("flow graph preview gestures", () => {
  it("previews the step being pointed at", () => {
    expect(previewAfter({ type: "hover", id: "s2" })).toBe("s2");
  });

  it("previews the focused step when nothing is pointed at", () => {
    expect(previewAfter({ type: "focus", id: "s3" })).toBe("s3");
  });

  /** A reader can hover one step while another still holds keyboard focus. */
  it("lets the pointer win over a step that still holds focus", () => {
    expect(previewAfter({ type: "focus", id: "s9" }, { type: "hover", id: "s2" })).toBe("s2");
  });

  /**
   * Focus stays on the node after Enter, so without spending that gesture the
   * reader asks for the path through a step and keeps getting the hop into it.
   */
  it("stops previewing a step opened from the keyboard", () => {
    expect(previewAfter({ type: "focus", id: "s5" }, { type: "activate", id: "s5" })).toBeNull();
  });

  it("stops previewing a step opened by click while the pointer rests on it", () => {
    expect(previewAfter({ type: "hover", id: "s5" }, { type: "activate", id: "s5" })).toBeNull();
  });

  it("still previews a different step while one is open", () => {
    expect(
      previewAfter(
        { type: "hover", id: "s5" },
        { type: "activate", id: "s5" },
        { type: "unhover" },
        { type: "hover", id: "s6" }
      )
    ).toBe("s6");
  });

  /**
   * The suppression belongs to the gesture, not the step. Tab away and back is
   * a new gesture, and must preview again rather than stay silent.
   */
  it("previews again after focus leaves the opened step and returns", () => {
    expect(
      previewAfter(
        { type: "focus", id: "a" },
        { type: "activate", id: "a" },
        { type: "focus", id: "b" },
        { type: "focus", id: "a" }
      )
    ).toBe("a");
  });

  it("previews again after the pointer leaves the opened step and returns", () => {
    expect(
      previewAfter(
        { type: "hover", id: "a" },
        { type: "activate", id: "a" },
        { type: "unhover" },
        { type: "hover", id: "a" }
      )
    ).toBe("a");
  });

  /**
   * Leaving with the pointer must not revive a preview of the step the
   * keyboard opened and never left.
   */
  it("keeps a keyboard-opened step silent while its focus never moved", () => {
    expect(
      previewAfter(
        { type: "focus", id: "a" },
        { type: "activate", id: "a" },
        { type: "hover", id: "b" },
        { type: "unhover" }
      )
    ).toBeNull();
  });
});

describe("computeFlowGraphEmphasis traversal cost", () => {
  /**
   * "Alla föregående" makes the edge count quadratic in steps, so rescanning
   * every edge for every reached node was cubic. Each edge should be looked
   * at a bounded number of times instead.
   */
  it("looks at each edge a bounded number of times on a dense graph", () => {
    const nodes = Array.from({ length: 120 }, (_, i) => `s${i}`);
    const dense: FlowGraphEmphasisEdge[] = [];
    for (let target = 1; target < nodes.length; target += 1) {
      for (let source = 0; source < target; source += 1) {
        dense.push({ id: `e-${source}-${target}`, source: nodes[source], target: nodes[target] });
      }
    }
    let reads = 0;
    const counted = dense.map((edge) => ({
      id: edge.id,
      get source() {
        reads += 1;
        return edge.source;
      },
      get target() {
        reads += 1;
        return edge.target;
      }
    }));

    const emphasis = computeFlowGraphEmphasis({
      edges: counted,
      activeId: "s60",
      previewId: null
    });

    expect(Object.keys(emphasis.litNodes).length).toBe(nodes.length);
    // Indexing reads each edge's two ends once; the walks then read one end
    // per edge at most once in each direction.
    expect(reads).toBeLessThanOrEqual(dense.length * 4);
  });
});
