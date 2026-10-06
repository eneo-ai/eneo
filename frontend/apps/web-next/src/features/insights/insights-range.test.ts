import { describe, expect, it } from "vitest";
import {
  insightPartnerQuery,
  insightRangeOfDays,
  insightRangeParams,
  isoDate,
  nextDay
} from "./insights-range";

describe("insight ranges", () => {
  it("writes local calendar dates and steps over month ends", () => {
    expect(isoDate(new Date(2026, 9, 2))).toBe("2026-10-02");
    expect(nextDay("2026-10-31")).toBe("2026-11-01");
    expect(nextDay("2028-02-28")).toBe("2028-02-29");
  });

  it("covers the last n days up to today", () => {
    expect(insightRangeOfDays(30, new Date(2026, 9, 2, 15))).toEqual({
      start: "2026-09-02",
      end: "2026-10-02"
    });
    expect(insightRangeOfDays(7, new Date(2026, 0, 3))).toEqual({
      start: "2025-12-27",
      end: "2026-01-03"
    });
  });

  it("includes the whole end day: the exclusive bound is the next day's midnight", () => {
    const params = insightRangeParams({ start: "2026-09-02", end: "2026-10-02" });
    expect(params.fromDate).toBe("2026-09-02");
    expect(params.toDate).toBe("2026-10-03");
    expect(params.startTime).toBe(new Date("2026-09-02T00:00:00").toISOString());
    expect(params.endTime).toBe(new Date("2026-10-03T00:00:00").toISOString());
  });

  it("asks about the assistant or the group chat", () => {
    expect(insightPartnerQuery({ type: "assistant", id: "a" })).toEqual({ assistant_id: "a" });
    expect(insightPartnerQuery({ type: "group-chat", id: "g" })).toEqual({ group_chat_id: "g" });
  });
});
