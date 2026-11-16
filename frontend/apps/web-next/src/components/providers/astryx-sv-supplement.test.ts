import astryxEn from "@astryxdesign/core/locales/en.json";
import astryxSv from "@astryxdesign/core/locales/sv-SE.json";
import { expect, it } from "vitest";
import { appSources } from "@/test/app-sources";
import { astryxSvSupplement } from "./astryx-sv-supplement";

// Astryx namespaces that other components render: the clear button inside
// inputs and the chat composer's trigger menu.
const INNER_PARTS = ["inputClearButton", "chatTriggerMenu"];

/** Astryx namespaces of the components the app imports (`@astryxdesign/core/Kbd` → `kbd`). */
function usedNamespaces(): Set<string> {
  const names = new Set(INNER_PARTS);
  for (const { text } of appSources)
    for (const [, module] of text.matchAll(/@astryxdesign\/core\/([A-Z]\w*)/g))
      names.add(module![0]!.toLowerCase() + module!.slice(1));
  return names;
}

it("has a Swedish string for every Astryx string of the components we use", () => {
  const used = usedNamespaces();
  const sv = { ...astryxSvSupplement, ...astryxSv };
  const missing = Object.keys(astryxEn).filter(
    (key) => used.has(key.split(".")[1]!) && !(key in sv)
  );
  expect(missing).toEqual([]);
});

it("only supplements keys Astryx has", () => {
  expect(Object.keys(astryxSvSupplement).filter((key) => !(key in astryxEn))).toEqual([]);
});
