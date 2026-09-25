// @vitest-environment jsdom
import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  dayRelation,
  firstNameOf,
  formatFileSize,
  formatSeconds,
  greetingFor,
  historyBucket
} from "./format";
import { groupSessions } from "./history-panel";
import { LiveRegion, useLiveRegion } from "./live-region";

afterEach(cleanup);

describe("chat formatting", () => {
  it("formats durations and file sizes the Swedish way", () => {
    expect(formatSeconds(14_600, "sv")).toBe("14,6 s");
    expect(formatSeconds(600, "en")).toBe("0.6 s");
    expect(formatFileSize(188_416, "sv")).toBe("184 kB");
    expect(formatFileSize(1_258_291, "sv")).toBe("1,2 MB");
    expect(formatFileSize(0, "sv")).toBe("0 B");
  });

  it("greets by time of day", () => {
    expect(greetingFor(7)).toBe("morning");
    expect(greetingFor(12)).toBe("day");
    expect(greetingFor(19)).toBe("evening");
    expect(greetingFor(2)).toBe("evening");
  });

  it("uses the first word of the username, else the e-mail's local part", () => {
    expect(firstNameOf({ username: "Anna Lind", email: "a@x.se" })).toBe("Anna");
    expect(firstNameOf({ username: "anna.lind", email: "a@x.se" })).toBe("anna.lind");
    expect(firstNameOf({ username: null, email: "anna.lind@sundsvall.se" })).toBe("anna.lind");
  });

  it("relates dates to today for timestamps and history groups", () => {
    const now = new Date(2026, 8, 25, 12, 0);
    expect(dayRelation(new Date(2026, 8, 25, 9, 42), now)).toBe("today");
    expect(dayRelation(new Date(2026, 8, 24, 23, 59), now)).toBe("yesterday");
    expect(dayRelation(new Date(2026, 8, 12), now)).toBe("earlier");
    expect(historyBucket(new Date(2026, 8, 21), now)).toBe("week");
    expect(historyBucket(new Date(2026, 8, 1), now)).toBe("month");
    expect(historyBucket(new Date(2026, 5, 1), now)).toBe("older");
  });

  it("groups newest-first sessions into consecutive date buckets", () => {
    const now = new Date(2026, 8, 25, 12, 0).getTime();
    const sessions = [
      { id: "1", name: "A", updated_at: new Date(2026, 8, 25, 9).toISOString() },
      { id: "2", name: "B", updated_at: new Date(2026, 8, 25, 8).toISOString() },
      { id: "3", name: "C", updated_at: new Date(2026, 8, 24, 8).toISOString() },
      { id: "4", name: "D", created_at: new Date(2025, 1, 1).toISOString() }
    ];
    expect(
      groupSessions(sessions, now).map((group) => [group.bucket, group.sessions.map((s) => s.id)])
    ).toEqual([
      ["today", ["1", "2"]],
      ["yesterday", ["3"]],
      ["older", ["4"]]
    ]);
    expect(groupSessions(sessions, null)).toEqual([{ bucket: null, sessions }]);
  });
});

function Announcer({ message }: { message: string }) {
  const { regionRef, announce } = useLiveRegion();
  return (
    <>
      <LiveRegion regionRef={regionRef} />
      <button type="button" onClick={() => announce(message)}>
        announce
      </button>
    </>
  );
}

describe("chat live region", () => {
  it("starts empty and receives short messages, then clears", () => {
    vi.useFakeTimers();
    render(<Announcer message="Svaret är klart" />);
    const region = screen.getByRole("status");
    expect(region.getAttribute("aria-live")).toBe("polite");
    expect(region.textContent).toBe("");
    act(() => screen.getByRole("button").click());
    act(() => vi.advanceTimersByTime(60));
    expect(region.textContent).toBe("Svaret är klart");
    act(() => vi.advanceTimersByTime(5_000));
    expect(region.textContent).toBe("");
    vi.useRealTimers();
  });
});
