// @vitest-environment jsdom
import { readFileSync } from "node:fs";
import path from "node:path";
import { act, renderHook } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { setViewport, type Viewport } from "@/test/setup-dom";
import { PHONE_SCREEN_QUERY, usePhoneScreen } from "./use-media-match";

const coarse = (width: number, height: number): Viewport => ({ width, height, pointer: "coarse" });
const fine = (width: number, height: number): Viewport => ({ width, height, pointer: "fine" });

// A phone's layout: narrower than 768 px, or a touch screen under 500 px tall and under 1024 px
// wide (a phone turned sideways). Its shortest is about 330 px, its tallest 430 px; an iPad is
// 744 px or more tall, and 1024 px or more wide when it is short with its keyboard up.
const PHONE_LAYOUT: [string, Viewport][] = [
  ["a small phone upright", coarse(320, 568)],
  ["a phone upright", coarse(390, 844)],
  ["a narrow desktop window", fine(700, 800)],
  ["an iPhone 14 turned", coarse(844, 390)],
  ["an iPhone Pro Max turned", coarse(932, 430)],
  ["an iPhone SE turned", coarse(667, 375)]
];

const TABLET_LAYOUT: [string, Viewport][] = [
  ["an iPad upright", coarse(820, 1180)],
  ["an iPad turned", coarse(1180, 820)],
  ["an iPad mini turned", coarse(1024, 768)],
  ["an iPad turned with its keyboard up", coarse(1180, 470)],
  ["a laptop", fine(1280, 800)],
  ["a short desktop window as wide as a turned phone", fine(844, 390)]
];

// What a phone and a tall window got before a turned phone counted as one: unchanged.
const UNCHANGED: [string, Viewport, boolean][] = [
  ["an iPad split a third", coarse(375, 820), true],
  ["an iPad Pro split a third", coarse(507, 1180), true],
  ["an iPad split in half", coarse(590, 820), true],
  ["a narrow window just under 768 px", fine(767, 1000), true],
  ["an iPad split two thirds", coarse(780, 820), false],
  ["a tall touch window of 768 px", coarse(768, 1024), false],
  ["a touch window of 768 px, 500 px tall", coarse(768, 500), false]
];

/** The media list of a custom variant in globals.css, as written there. */
function variantMedia(name: string): string {
  const css = readFileSync(
    path.resolve(import.meta.dirname, "../../styles/globals.css"),
    "utf8"
  ).replace(/\s+/g, " ");
  const media = new RegExp(`@custom-variant ${name} \\{ @media ([^{]+) \\{ @slot; \\} \\}`).exec(
    css
  )?.[1];
  if (!media) throw new Error(`no @custom-variant ${name} in globals.css`);
  return media.trim();
}

describe("a phone's layout", () => {
  const cases: [string, Viewport, boolean][] = [
    ...PHONE_LAYOUT.map(([name, size]): [string, Viewport, boolean] => [name, size, true]),
    ...TABLET_LAYOUT.map(([name, size]): [string, Viewport, boolean] => [name, size, false])
  ];

  it.each(cases)("%s at %o: phone %s", (_name, size, phone) => {
    setViewport(size);
    expect(renderHook(() => usePhoneScreen()).result.current).toBe(phone);
    expect(window.matchMedia(PHONE_SCREEN_QUERY).matches).toBe(phone);
  });

  it.each(UNCHANGED)("leaves %s at %o as it was: phone %s", (_name, size, phone) => {
    setViewport(size);
    expect(renderHook(() => usePhoneScreen()).result.current).toBe(phone);
    expect(window.matchMedia(PHONE_SCREEN_QUERY).matches).toBe(phone);
  });

  it("follows a phone turned sideways and back", () => {
    setViewport(coarse(390, 844));
    const { result } = renderHook(() => usePhoneScreen());
    act(() => setViewport(coarse(844, 390)));
    expect(result.current).toBe(true);
    act(() => setViewport(coarse(1180, 820)));
    expect(result.current).toBe(false);
  });

  // CSS (`phone:`, `wide:`) and JS must pick the same layout, or a block JS shows is hidden by CSS.
  it.each([...cases, ...UNCHANGED])("CSS agrees on %s at %o", (_name, size, phone) => {
    setViewport(size);
    expect(window.matchMedia(variantMedia("phone")).matches).toBe(phone);
    expect(window.matchMedia(variantMedia("wide")).matches).toBe(!phone);
  });
});
