import { describe, expect, it } from "vitest";

import { getFlowRunStatusView } from "./flowRunStatusPresentation";

const translations = {
  completed: () => "Completed",
  failed: () => "Failed",
  queued: () => "Queued",
  running: () => "Running",
  cancelled: () => "Cancelled"
};

describe("getFlowRunStatusView", () => {
  it("maps completed status to positive status visuals", () => {
    expect(getFlowRunStatusView("completed", translations)).toEqual({
      label: "Completed",
      textClass: "text-positive-stronger",
      dotClass: "bg-positive-default",
      pulseDot: false
    });
  });

  it("maps cancelled status to warning status visuals", () => {
    expect(getFlowRunStatusView("cancelled", translations)).toEqual({
      label: "Cancelled",
      textClass: "text-warning-stronger",
      dotClass: "bg-warning-default",
      pulseDot: false
    });
  });

  it("maps pending status to queued label with muted visuals", () => {
    expect(getFlowRunStatusView("pending", translations)).toEqual({
      label: "Queued",
      textClass: "text-secondary",
      dotClass: "bg-secondary",
      pulseDot: false
    });
  });

  it("falls back to raw unknown status with muted visuals", () => {
    expect(getFlowRunStatusView("mystery-status", translations)).toEqual({
      label: "mystery-status",
      textClass: "text-secondary",
      dotClass: "bg-secondary",
      pulseDot: false
    });
  });

  it("models running pulse separately from dot color", () => {
    expect(getFlowRunStatusView("running", translations)).toEqual({
      label: "Running",
      textClass: "text-accent-stronger",
      dotClass: "bg-accent-default",
      pulseDot: true
    });
  });
});
