import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { readable } from "svelte/store";
import { m } from "$lib/paraglide/messages";

const userMode = vi.hoisted(() => ({ current: "user" as "user" | "power_user" }));
vi.mock("$lib/features/flows/FlowUserMode", () => ({
  getFlowUserMode: () => readable(userMode.current)
}));

import FlowRunProgressView from "./FlowRunProgressView.svelte";

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  userMode.current = "user";
});

const completedStep = {
  stepOrder: 1,
  label: "Summarize",
  status: "completed" as const,
  inputPayload: { text: "källa" },
  outputPayload: { text: "done", structured: { beslut: "bifall" } },
  resultFiles: [],
  numTokensInput: 12,
  numTokensOutput: 34
};

describe("FlowRunProgressView", () => {
  it("keeps the raw step input, the data format and token counts out of the default mode", () => {
    render(FlowRunProgressView, { props: { snapshot: { steps: [completedStep] } } });

    expect(screen.getByText(/"bifall"/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: m.flow_run_input() })).toBeNull();
    expect(screen.queryByText(m.flow_run_structured_json_badge())).toBeNull();
    expect(screen.queryByText(m.flow_run_tokens())).toBeNull();
  });

  it("shows them in Advanced", () => {
    userMode.current = "power_user";
    render(FlowRunProgressView, { props: { snapshot: { steps: [completedStep] } } });

    expect(screen.getByRole("button", { name: m.flow_run_input() })).toBeTruthy();
    expect(screen.getByText(m.flow_run_structured_json_badge())).toBeTruthy();
    expect(screen.getByText(m.flow_run_tokens())).toBeTruthy();
  });

  it("opens a step's input on the first click and closes it on the second", async () => {
    userMode.current = "power_user";
    render(FlowRunProgressView, {
      props: {
        snapshot: {
          steps: [
            {
              stepOrder: 1,
              label: "Transcribe",
              status: "completed",
              inputPayload: { transcription: { model: "whisper" } },
              outputPayload: { text: "done" },
              resultFiles: []
            }
          ]
        }
      }
    });

    const trigger = screen.getByRole("button", { name: m.flow_run_input() });
    expect(trigger.getAttribute("aria-expanded")).toBe("false");

    await fireEvent.click(trigger);
    await waitFor(() => expect(trigger.getAttribute("aria-expanded")).toBe("true"));
    expect(screen.getByText(/"whisper"/)).toBeTruthy();

    await fireEvent.click(trigger);
    await waitFor(() => expect(trigger.getAttribute("aria-expanded")).toBe("false"));
  });
});
