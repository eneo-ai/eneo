import { describe, expect, it } from "vitest";
import {
  mentionNames,
  mentionParts,
  mentionPattern,
  mentionText,
  parseBareMention,
  parseMention
} from "./mentions";

describe("mentions", () => {
  it("writes a mention and reads it back, name and key alike", () => {
    for (const [name, scheme, key] of [
      ["Chattmodell", "setting", "completion_model"],
      ["AI-inställningar", "setting", "section:ai"],
      ["Resonemangsnivå", "setting", "completion_model_kwargs.reasoning_effort"],
      ["Bedömning", "step", "3f1c-22"]
    ] as const) {
      const raw = mentionText(name, scheme, key);
      expect(raw).toBe(`@[${name}](${scheme}:${key})`);
      expect(parseMention(raw, scheme)).toEqual({ name, key });
      expect(mentionParts(`Se ${raw}.`, scheme)).toEqual([
        { kind: "text", text: "Se " },
        { kind: "mention", raw, name, key },
        { kind: "text", text: "." }
      ]);
    }
  });

  it("drops brackets from a name and writes an empty one as a question mark", () => {
    expect(mentionText(" Läs [bilaga] ", "step", "s")).toBe("@[Läs bilaga](step:s)");
    expect(mentionText("  ", "setting", "name")).toBe("@[?](setting:name)");
  });

  it("reads only its own scheme, and nothing across a line", () => {
    const text = "@[Steg](step:1) och @[Namn](setting:name) och @[Två\nrader](setting:prompt)";
    expect(mentionParts(text, "setting").filter((part) => part.kind === "mention")).toEqual([
      { kind: "mention", raw: "@[Namn](setting:name)", name: "Namn", key: "name" }
    ]);
    expect(parseMention("@[Steg](step:1)", "setting")).toBeNull();
    expect(parseMention("@[Namn](setting:name) ", "setting")).toBeNull();
    expect([
      ..."a @[A](setting:x) b @[B](setting:y)".matchAll(mentionPattern("setting"))
    ]).toHaveLength(2);
  });

  it("leaves a text without mentions as one part, and an empty one as none", () => {
    expect(mentionParts("Hej", "setting")).toEqual([{ kind: "text", text: "Hej" }]);
    expect(mentionParts("", "setting")).toEqual([]);
  });

  it("reads a mention without its scheme, the whole address as the key, but not a link", () => {
    expect(parseBareMention("@[Namn](name)")).toEqual({ name: "Namn", key: "name" });
    expect(parseBareMention("@[Allmänt](section:general)")).toEqual({
      name: "Allmänt",
      key: "section:general"
    });
    expect(parseBareMention("@[Bedömning](3f1c-22)")).toEqual({
      name: "Bedömning",
      key: "3f1c-22"
    });
    for (const raw of [
      "@[text](https://example.com)",
      "@[text](mailto:kontakt@example.se)",
      "@[text](/spaces)",
      "@[text](./bilaga)",
      "@[text](#avsnitt)",
      "[text](name)",
      "@[Namn](name) ",
      "@[Namn](två ord)"
    ]) {
      expect(parseBareMention(raw)).toBeNull();
    }
  });

  it("reads every mention by its name, whatever its scheme, and one cut off at the end too", () => {
    expect(
      mentionNames("Hjälp mig skriva @[Instruktioner](setting:prompt) och @[Steg 1](step:abc)")
    ).toBe("Hjälp mig skriva Instruktioner och Steg 1");
    expect(mentionNames("Läs @[Steg 2](step:a")).toBe("Läs Steg 2");
    expect(mentionNames("Läs @[Ste")).toBe("Läs Ste");
    expect(mentionNames("Inga omnämnanden här.")).toBe("Inga omnämnanden här.");
  });
});
