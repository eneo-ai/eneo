import { describe, expect, it } from "vitest";
import { embedLanguageRedirect, isEmbedPage } from "./embedLanguage";

const url = (path: string) => new URL(`https://eneo.kommun.se${path}`);
const QUERY = "?origin=https%3A%2F%2Fwww.kommun.se&scheme=light";

describe("isEmbedPage", () => {
  it("recognises the embed page in either language", () => {
    expect(isEmbedPage(url(`/embed/wgt_x${QUERY}`))).toBe(true);
    expect(isEmbedPage(url("/en/embed/wgt_x?mode=full"))).toBe(true);
    expect(isEmbedPage(url("/sv/embed/wgt_x"))).toBe(true);
  });

  it("leaves every other page to the ordinary language handling", () => {
    expect(isEmbedPage(url("/"))).toBe(false);
    expect(isEmbedPage(url("/en/spaces/embed/wgt_x"))).toBe(false);
    expect(isEmbedPage(url("/embedded/wgt_x"))).toBe(false);
    expect(isEmbedPage(url("/widget/v1/eneo.js"))).toBe(false);
  });
});

describe("embedLanguageRedirect", () => {
  it("moves the page to the widget's fixed language and keeps the query", () => {
    expect(embedLanguageRedirect(url(`/embed/wgt_x${QUERY}`), "en")).toBe(
      `/en/embed/wgt_x${QUERY}`
    );
    expect(embedLanguageRedirect(url(`/en/embed/wgt_x${QUERY}`), "sv")).toBe(
      `/embed/wgt_x${QUERY}`
    );
    expect(embedLanguageRedirect(url("/en/embed/wgt_x?mode=full"), "sv")).toBe(
      "/embed/wgt_x?mode=full"
    );
  });

  it("leaves a page already in the right language, or one following the host, alone", () => {
    expect(embedLanguageRedirect(url(`/en/embed/wgt_x${QUERY}`), "en")).toBeNull();
    expect(embedLanguageRedirect(url(`/embed/wgt_x${QUERY}`), "sv")).toBeNull();
    expect(embedLanguageRedirect(url(`/en/embed/wgt_x${QUERY}`), "auto")).toBeNull();
    expect(embedLanguageRedirect(url(`/embed/wgt_x${QUERY}`), "auto")).toBeNull();
  });
});
