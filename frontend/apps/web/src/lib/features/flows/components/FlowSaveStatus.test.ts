// @vitest-environment jsdom

import { cleanup, render, screen } from "@testing-library/svelte";
import { afterEach, describe, expect, it, vi } from "vitest";

import { m } from "$lib/paraglide/messages";

import FlowSaveStatus from "./FlowSaveStatus.svelte";

afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

describe("FlowSaveStatus", () => {
  it("keeps showing saved while the canonical status is saved", async () => {
    vi.useFakeTimers();
    render(FlowSaveStatus, { status: "saved" });

    expect(screen.getByText(m.flow_save_status_saved())).toBeTruthy();

    await vi.advanceTimersByTimeAsync(2500);

    expect(screen.getByText(m.flow_save_status_saved())).toBeTruthy();
    expect(screen.queryByText(m.flow_save_status_unsaved())).toBeNull();
  });

  it("renders the unsaved label only when the canonical status is unsaved", () => {
    render(FlowSaveStatus, { status: "unsaved" });

    expect(screen.getByText(m.flow_save_status_unsaved())).toBeTruthy();
  });
});
