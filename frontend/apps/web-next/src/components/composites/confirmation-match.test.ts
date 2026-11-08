import { expect, it } from "vitest";
import { confirmationMatches } from "./confirmation-match";

it("matches the name, ignoring the space a suggestion adds and the form of å, ä and ö", () => {
  expect(confirmationMatches("Upphandling", "Upphandling")).toBe(true);
  expect(confirmationMatches("Upphandling ", "Upphandling")).toBe(true);
  expect(confirmationMatches("Förvaltning", "Förvaltning")).toBe(true);
});

it("stays exact about everything else", () => {
  expect(confirmationMatches("upphandling", "Upphandling")).toBe(false);
  expect(confirmationMatches("Upphandlin", "Upphandling")).toBe(false);
  expect(confirmationMatches("Upp handling", "Upphandling")).toBe(false);
});
