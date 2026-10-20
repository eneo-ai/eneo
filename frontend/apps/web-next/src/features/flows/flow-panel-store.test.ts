import { describe, expect, it } from "vitest";
import { FlowPanelStore } from "./flow-panel-store";

describe("FlowPanelStore steps", () => {
  it("opens a step on the definition tab and goes back to the overview", () => {
    const store = new FlowPanelStore({ flowId: "flow-1", tab: "runs" });
    store.openStep("summary");
    expect(store.stepKey).toBe("summary");
    expect(store.tab).toBe("definition");

    store.openStep("intro");
    expect(store.stepKey).toBe("intro");
    store.closeStep();
    expect(store.stepKey).toBe(null);
  });

  it("closes the step when a run is shown", () => {
    const store = new FlowPanelStore({ flowId: "flow-1" });
    store.openStep("summary");
    store.showRun("run-1");
    expect(store.stepKey).toBe(null);
    expect(store.tab).toBe("runs");
  });

  it("starts in view mode and notifies on a mode change", () => {
    const store = new FlowPanelStore({ flowId: "flow-1" });
    let changes = 0;
    store.subscribe(() => changes++);
    expect(store.mode).toBe("view");
    store.setMode("edit");
    store.setMode("edit");
    expect(store.mode).toBe("edit");
    expect(changes).toBe(1);
  });
});

describe("FlowPanelStore editor", () => {
  it("opens the editor for a step and goes back to reading it", () => {
    const store = new FlowPanelStore({ flowId: "flow-1" });
    store.openStep("summary", { edit: true });
    expect(store.stepEditing).toBe(true);
    store.closeEditor();
    expect(store.stepEditing).toBe(false);
    expect(store.stepKey).toBe("summary");
  });

  it("opens a new step at a position and leaves to the overview on cancel", () => {
    const store = new FlowPanelStore({ flowId: "flow-1" });
    store.openNewStep("llm", 2);
    expect(store.newStep).toEqual({ kind: "llm", index: 2 });
    expect(store.stepEditing).toBe(true);
    store.closeEditor();
    expect(store.newStep).toBe(null);
    expect(store.stepKey).toBe(null);
  });
});
