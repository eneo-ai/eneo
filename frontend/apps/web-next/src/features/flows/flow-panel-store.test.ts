import { describe, expect, it } from "vitest";
import { FlowPanelStore } from "./flow-panel-store";

/** The side panel as the store steers it: a maximised flag it can set. */
function layout(maximised = false) {
  const state = { maximised, setMaximised: (on: boolean) => void (state.maximised = on) };
  return state;
}

describe("FlowPanelStore steps", () => {
  it("opens a step maximised and puts the panel back as it was on close", () => {
    const store = new FlowPanelStore({ flowId: "flow-1", tab: "runs" });
    const panel = layout(false);
    store.openStep("summary", panel);
    expect(store.stepKey).toBe("summary");
    expect(store.tab).toBe("definition");
    expect(panel.maximised).toBe(true);

    // Moving between steps keeps the layout; closing restores the original.
    store.openStep("intro", panel);
    expect(panel.maximised).toBe(true);
    store.closeStep(panel);
    expect(store.stepKey).toBe(null);
    expect(panel.maximised).toBe(false);
  });

  it("leaves a panel that was already maximised maximised", () => {
    const store = new FlowPanelStore({ flowId: "flow-1" });
    const panel = layout(true);
    store.openStep("summary", panel);
    store.closeStep(panel);
    expect(panel.maximised).toBe(true);
  });

  it("closes the step when a run is shown", () => {
    const store = new FlowPanelStore({ flowId: "flow-1" });
    store.openStep("summary", layout());
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
    const panel = layout();
    store.openStep("summary", panel, { edit: true });
    expect(store.stepEditing).toBe(true);
    store.closeEditor(panel);
    expect(store.stepEditing).toBe(false);
    expect(store.stepKey).toBe("summary");
    expect(panel.maximised).toBe(true);
  });

  it("opens a new step at a position and leaves to the overview on cancel", () => {
    const store = new FlowPanelStore({ flowId: "flow-1" });
    const panel = layout();
    store.openNewStep("llm", 2, panel);
    expect(store.newStep).toEqual({ kind: "llm", index: 2 });
    expect(store.stepEditing).toBe(true);
    expect(panel.maximised).toBe(true);
    store.closeEditor(panel);
    expect(store.newStep).toBe(null);
    expect(store.stepKey).toBe(null);
    expect(panel.maximised).toBe(false);
  });
});
