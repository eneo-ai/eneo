import { describe, expect, it } from "vitest";
import { embedLanguageRedirect } from "./embedLanguage";

const url = (path: string) => new URL(`https://eneo.kommun.se${path}`);
const QUERY = "?origin=https%3A%2F%2Fwww.kommun.se&scheme=light";

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
