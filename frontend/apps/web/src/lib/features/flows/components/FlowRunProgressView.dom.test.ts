import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/svelte";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { m } from "$lib/paraglide/messages";
import FlowRunProgressView from "./FlowRunProgressView.svelte";

beforeEach(() => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
});

afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

describe("FlowRunProgressView", () => {
  it("opens a step's input on the first click and closes it on the second", async () => {
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
