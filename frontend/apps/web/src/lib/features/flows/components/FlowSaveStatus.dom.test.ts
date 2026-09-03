import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, beforeAll, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowSaveStatus from "./FlowSaveStatus.svelte";

beforeAll(() => {
  // jsdom has no Web Animations API; the badge's fade is a no-op here.
  if (typeof Element.prototype.animate !== "function") {
    Element.prototype.animate = (() =>
      ({
        finished: Promise.resolve(),
        cancel() {},
        onfinish: null
      }) as unknown as Animation) as never;
  }
});

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

const saved = () => m.flow_save_status_saved();
const saving = () => m.flow_save_status_saving();
const unsaved = () => m.flow_save_status_unsaved();

describe("FlowSaveStatus", () => {
  it("keeps showing saved while the canonical status is saved", async () => {
    vi.useFakeTimers();
    render(FlowSaveStatus, { status: "saved" });

    expect(screen.getByText(saved())).toBeTruthy();

    await vi.advanceTimersByTimeAsync(2500);

    expect(screen.getByText(saved())).toBeTruthy();
    expect(screen.queryByText(unsaved())).toBeNull();
  });

  it("never shows a typing pause's quick save", async () => {
    // unsaved -> saving -> saved inside a second is what every keystroke pause
    // produces; none of it is worth a badge change.
    vi.useFakeTimers();
    const { rerender } = render(FlowSaveStatus, { status: "saved" });

    await rerender({ status: "unsaved" });
    await vi.advanceTimersByTimeAsync(500);
    expect(screen.getByText(saved())).toBeTruthy();

    await rerender({ status: "saving" });
    await vi.advanceTimersByTimeAsync(700);
    expect(screen.getByText(saved())).toBeTruthy();

    await rerender({ status: "saved" });
    await vi.advanceTimersByTimeAsync(2000);
    expect(screen.getByText(saved())).toBeTruthy();
    expect(screen.queryByText(saving())).toBeNull();
    expect(screen.queryByText(unsaved())).toBeNull();
  });

  it("shows a slow save as saving, and holds it long enough to be read", async () => {
    vi.useFakeTimers();
    const { rerender } = render(FlowSaveStatus, { status: "saved" });

    await rerender({ status: "saving" });
    await vi.advanceTimersByTimeAsync(800);
    expect(screen.getByText(saving())).toBeTruthy();

    // The save completes 100 ms after the badge appeared: it stays for its
    // minimum, then turns into saved.
    await vi.advanceTimersByTimeAsync(100);
    await rerender({ status: "saved" });
    await vi.advanceTimersByTimeAsync(400);
    expect(screen.getByText(saving())).toBeTruthy();

    await vi.advanceTimersByTimeAsync(200);
    expect(screen.getByText(saved())).toBeTruthy();
  });

  it("shows unsaved only for changes that stay unsaved", async () => {
    vi.useFakeTimers();
    const { rerender } = render(FlowSaveStatus, { status: "saved" });

    await rerender({ status: "unsaved" });
    await vi.advanceTimersByTimeAsync(1400);
    expect(screen.getByText(saved())).toBeTruthy();

    await vi.advanceTimersByTimeAsync(200);
    expect(screen.getByText(unsaved())).toBeTruthy();
  });

  it("starts from the status it is given", () => {
    render(FlowSaveStatus, { status: "unsaved" });

    expect(screen.getByText(unsaved())).toBeTruthy();
  });
});
