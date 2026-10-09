import { describe, expect, it } from "vitest";
import { answerText } from "./answerText";

describe("answerText", () => {
  it("reads the words without Markdown syntax or citation markers", () => {
    expect(
      answerText(
        'Biblioteket har **öppet** 9–17 <inref id="doc-1"/>. Se [webben](https://kommun.se) och `kod`.'
      )
    ).toBe("Biblioteket har öppet 9–17. Se webben och kod.");
  });

  it("puts each block on its own line and keeps list numbers", () => {
    const markdown = [
      "## Öppettider & kontakt",
      "",
      "- Måndag *stängt*",
      "- Tisdag 9–17",
      "",
      "3. Ring",
      "4. Mejla",
      "",
      "> Tänk på helgerna",
      "",
      "```",
      "tel 060-19 10 00",
      "```"
    ].join("\n");
    expect(answerText(markdown)).toBe(
      [
        "Öppettider & kontakt",
        "Måndag stängt",
        "Tisdag 9–17",
        "3. Ring",
        "4. Mejla",
        "Tänk på helgerna",
        "tel 060-19 10 00"
      ].join("\n")
    );
  });

  it("reads tables row by row and drops raw HTML and images' markup", () => {
    const markdown =
      "| Dag | Tid |\n|---|---|\n| Mån | 9–17 |\n\nText <b>fet</b> ![Kommunens logga](logo.png)";
    expect(answerText(markdown)).toBe("Dag, Tid\nMån, 9–17\nText fet Kommunens logga");
  });

  it("is empty for an answer with nothing to read", () => {
    expect(answerText("")).toBe("");
    expect(answerText('<inref id="doc-1"/>')).toBe("");
  });
});
