import { afterEach, describe, expect, test, vi } from "vitest";

import { getDeprecationStatus } from "./formatModelStats";

function setToday(date: string): void {
  vi.useFakeTimers();
  vi.setSystemTime(`${date}T12:00:00.000Z`);
}

afterEach(() => {
  vi.useRealTimers();
});

describe("getDeprecationStatus", () => {
  test("keeps models active until six months before deprecation", () => {
    setToday("2026-08-27");

    expect(getDeprecationStatus({ deprecation_date: "2027-03-01" })).toEqual({
      kind: "active",
      date: null
    });
  });

  test("marks a model as retiring on the six-month boundary", () => {
    setToday("2026-08-27");

    expect(getDeprecationStatus({ deprecation_date: "2027-02-27" })).toEqual({
      kind: "retiring",
      date: "2027-02-27"
    });
  });

  test("keeps a model active one day outside the warning window", () => {
    setToday("2026-08-27");

    expect(getDeprecationStatus({ deprecation_date: "2027-02-28" })).toEqual({
      kind: "active",
      date: null
    });
  });

  test("clamps the warning start to the end of shorter months", () => {
    setToday("2027-02-28");

    expect(getDeprecationStatus({ deprecation_date: "2027-08-31" })).toEqual({
      kind: "retiring",
      date: "2027-08-31"
    });
  });

  test("marks a model as deprecated on its deprecation date", () => {
    setToday("2026-11-27");

    expect(getDeprecationStatus({ deprecation_date: "2026-11-27" })).toEqual({
      kind: "deprecated",
      date: "2026-11-27"
    });
  });

  test("keeps models without a deprecation date active", () => {
    setToday("2026-08-27");

    expect(getDeprecationStatus({ deprecation_date: null })).toEqual({
      kind: "active",
      date: null
    });
  });
});
