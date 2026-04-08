import { expect, test } from "vitest";
import { normalizePolicy, normalizePreferences } from "./notificationPreferences";

test("normalizePreferences migrates legacy day arrays to a single max value", () => {
  expect(
    normalizePreferences({
      enabled: true,
      days_before_expiry: [30, 14, 7, 3, 1]
    })
  ).toMatchObject({
    enabled: true,
    days_before_expiry: 30
  });
});

test("normalizePreferences falls back to default for invalid values", () => {
  expect(
    normalizePreferences({
      days_before_expiry: 0
    })
  ).toMatchObject({
    days_before_expiry: 30
  });
});

test("normalizePolicy clamps default days to the tenant max", () => {
  expect(
    normalizePolicy({
      default_days_before_expiry: [90, 30],
      max_days_before_expiry: 30
    })
  ).toMatchObject({
    default_days_before_expiry: 30,
    max_days_before_expiry: 30
  });
});
