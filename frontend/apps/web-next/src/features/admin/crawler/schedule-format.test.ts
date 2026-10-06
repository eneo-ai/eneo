import { describe, expect, it } from "vitest";
import {
  elapsedParts,
  intervalLabelKey,
  relativeDue,
  SCHEDULE_SORT_DIRECTIONS
} from "./schedule-format";

describe("relativeDue", () => {
  it("says how far a due time is from the server's as_of, in the nearest unit", () => {
    const asOf = "2026-09-10T09:00:00Z";
    expect(relativeDue("2026-09-10T09:20:00Z", asOf, "sv")).toBe("om 20 minuter");
    expect(relativeDue("2026-09-10T07:00:00Z", asOf, "sv")).toBe("för 2 timmar sedan");
    expect(relativeDue("2026-09-13T09:00:00Z", asOf, "sv")).toBe("om 3 dagar");
    expect(relativeDue("2026-09-11T09:00:00Z", asOf, "en")).toBe("in 24 hours");
  });
});

describe("elapsedParts", () => {
  it("splits the elapsed time into minutes and seconds, never negative", () => {
    expect(elapsedParts("2026-09-10T09:00:00Z", "2026-09-10T09:02:05Z")).toEqual({
      minutes: 2,
      seconds: 5
    });
    expect(elapsedParts("2026-09-10T09:02:05Z", "2026-09-10T09:00:00Z")).toEqual({
      minutes: 0,
      seconds: 0
    });
  });
});

describe("schedule labels", () => {
  it("maps intervals to their keys and sort columns to the server's direction", () => {
    expect(intervalLabelKey("every_other_day")).toBe("every_other_day");
    expect(SCHEDULE_SORT_DIRECTIONS.last_crawled).toBe("descending");
    expect(SCHEDULE_SORT_DIRECTIONS.url).toBe("ascending");
  });
});
