import { describe, expect, it } from "vitest";
import { m } from "$lib/paraglide/messages";
import { intervalLabel, relativeDue, sortDirections } from "./scheduleFormat";

const AS_OF = "2026-09-21T12:00:00Z";

describe("relativeDue", () => {
  it("uses minutes under an hour", () => {
    expect(relativeDue("2026-09-21T12:20:00Z", AS_OF, "en")).toBe("in 20 minutes");
    expect(relativeDue("2026-09-21T12:20:00Z", AS_OF, "sv")).toBe("om 20 minuter");
  });

  it("uses hours under two days and reads overdue targets as past", () => {
    expect(relativeDue("2026-09-21T10:00:00Z", AS_OF, "en")).toBe("2 hours ago");
    expect(relativeDue("2026-09-22T13:00:00Z", AS_OF, "en")).toBe("in 25 hours");
  });

  it("uses days beyond that", () => {
    expect(relativeDue("2026-09-24T12:00:00Z", AS_OF, "en")).toBe("in 3 days");
  });
});

describe("intervalLabel", () => {
  it("maps every interval to its message", () => {
    expect(intervalLabel("daily")).toBe(m.daily());
    expect(intervalLabel("every_other_day")).toBe(m.every_other_day());
    expect(intervalLabel("weekly")).toBe(m.weekly());
    expect(intervalLabel("never")).toBe(m.never());
  });
});

it("orders next due and url ascending but last crawled descending", () => {
  expect(sortDirections).toEqual({
    next_due: "ascending",
    last_crawled: "descending",
    url: "ascending"
  });
});
