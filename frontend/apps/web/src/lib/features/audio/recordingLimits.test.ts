import { describe, expect, it } from "vitest";
import { formatRecordingLength } from "./recordingLimits";

const HOUR = 3_600_000;

describe("formatRecordingLength", () => {
  it("says hours and minutes", () => {
    expect([5 * HOUR, 4.5 * HOUR, 45 * 60_000].map(formatRecordingLength)).toEqual([
      "5 h",
      "4 h 30 min",
      "45 min"
    ]);
  });
});
