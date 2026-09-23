import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it } from "vitest";

import { m } from "$lib/paraglide/messages";

import LiveTranscriptPanel from "./LiveTranscriptPanel.svelte";

afterEach(() => {
  cleanup();
});

const spoken = [
  { id: 0, text: "Hej och" },
  { id: 1, text: " välkomna." }
];

describe("LiveTranscriptPanel", () => {
  it("shows the text in a log named after the panel while it listens", () => {
    render(LiveTranscriptPanel, { status: "listening", pieces: spoken });

    const log = screen.getByRole("log", { name: m.live_transcription_heading() });
    expect(log.textContent).toBe("Hej och välkomna.");
    expect(screen.getByText(m.live_transcription_listening())).toBeTruthy();
  });

  it("says it is connecting and where the text will appear", () => {
    render(LiveTranscriptPanel, { status: "connecting", pieces: [] });

    expect(screen.getByText(m.live_transcription_connecting())).toBeTruthy();
    expect(screen.getByRole("log").textContent).toBe(m.live_transcription_empty());
  });

  it("says the live text stopped while the recording goes on, and keeps the text", () => {
    render(LiveTranscriptPanel, { status: "interrupted", pieces: spoken });

    const alert = screen.getByRole("alert");
    expect(alert.textContent).toContain(m.live_transcription_interrupted());
    expect(alert.textContent).toContain(m.live_transcription_interrupted_detail());
    expect(screen.getByRole("log").textContent).toBe("Hej och välkomna.");
    expect(screen.queryByText(m.live_transcription_listening())).toBeNull();
  });

  it("marks the text as a draft once the recording is done", () => {
    render(LiveTranscriptPanel, { status: "finished", pieces: spoken });

    expect(screen.getByText(m.live_transcription_draft_note())).toBeTruthy();
    expect(screen.queryByText(m.live_transcription_empty())).toBeNull();
  });

  it("shows nothing before a recording or after one that heard no speech", () => {
    const idle = render(LiveTranscriptPanel, { status: "idle", pieces: [] });
    expect(idle.container.textContent).toBe("");
    idle.unmount();

    const silent = render(LiveTranscriptPanel, { status: "finished", pieces: [] });
    expect(silent.container.textContent).toBe("");
  });
});
