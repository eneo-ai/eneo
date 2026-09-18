import { describe, expect, it } from "vitest";
import { getLocale, overwriteGetLocale } from "$lib/paraglide/runtime";
import { withLocale } from "./testLocale";

describe("withLocale", () => {
  it("restores the resolver, not the locale it happened to return", () => {
    // Stand in for the real url/cookie resolver: a function whose answer
    // depends on something outside itself.
    let ambient: "sv" | "en" = "sv";
    const resolver = () => ambient;
    overwriteGetLocale(resolver);

    const restore = withLocale("en");
    expect(getLocale()).toBe("en");
    restore();

    // The bug this guards: restoring `() => previousValue` pins the locale to
    // a constant, so changing what the resolver reads stops having any effect.
    ambient = "en";
    expect(getLocale()).toBe("en");
    ambient = "sv";
    expect(getLocale()).toBe("sv");
  });
});
