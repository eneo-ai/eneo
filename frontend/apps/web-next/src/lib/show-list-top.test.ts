// @vitest-environment jsdom
import { afterEach, describe, expect, it, vi } from "vitest";
import { DESKTOP_VIEWPORT, PHONE_VIEWPORT, setViewport } from "@/test/setup-dom";
import { showListTop } from "./show-list-top";

afterEach(() => vi.restoreAllMocks());

describe("showListTop", () => {
  it("brings the list's top into view on a touch screen only", () => {
    const list = document.createElement("div");
    const scrollIntoView = vi.fn();
    list.scrollIntoView = scrollIntoView;

    setViewport(DESKTOP_VIEWPORT);
    showListTop(list);
    expect(scrollIntoView).not.toHaveBeenCalled();

    setViewport(PHONE_VIEWPORT);
    showListTop(list);
    expect(scrollIntoView).toHaveBeenCalledWith({ block: "start" });
  });

  it("does nothing without a list", () => {
    setViewport(PHONE_VIEWPORT);
    expect(() => showListTop(null)).not.toThrow();
  });
});
