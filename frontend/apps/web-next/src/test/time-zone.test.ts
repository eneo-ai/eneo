import { expect, it } from "vitest";

it("runs date tests outside Stockholm and UTC", () => {
  // ICU releases use either IANA name for this same zone.
  expect(["Asia/Kolkata", "Asia/Calcutta"]).toContain(
    Intl.DateTimeFormat().resolvedOptions().timeZone
  );
  expect(new Date("2026-01-01T20:00:00Z").getTimezoneOffset()).toBe(-330);
});
