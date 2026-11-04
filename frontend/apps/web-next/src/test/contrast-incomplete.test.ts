// @vitest-environment jsdom
import axe, { type Result } from "axe-core";
import { afterEach, describe, expect, it } from "vitest";
import { incompleteCounts } from "../../tests/contrast-incomplete";

afterEach(() => {
  document.body.innerHTML = "";
});

/**
 * What axe reports for the page's unnamed buttons, passed off as contrast nodes:
 * jsdom has no layout for color-contrast, and the paths are axe's own either way.
 */
async function scan(html: string, reason = "bgOverlap") {
  document.body.innerHTML = html;
  const { violations } = await axe.run(document.body, {
    ancestry: true,
    runOnly: ["button-name"]
  });
  const nodes = violations[0]!.nodes.map((node) => ({
    ...node,
    any: [{ data: { messageKey: reason } }]
  }));
  return [{ id: "color-contrast", nodes }] as unknown as Result[];
}

const cell = (id: string) => `<td><button id="${id}"></button></td>`;

describe("incompleteCounts", () => {
  it("counts each place once, however many table rows repeat it", async () => {
    const rows = Array.from({ length: 40 }, (_, row) => `<tr>${cell(`row-${row}`)}</tr>`);
    const page = await scan(`<table><tbody>${rows.join("")}</tbody></table>`);
    expect(incompleteCounts(page)).toEqual({ bgOverlap: 1 });
  });

  it("counts each place once, however many list items repeat it", async () => {
    const items = [0, 1, 2].map((item) => `<li><a href="/s/${item}"><button></button></a></li>`);
    expect(incompleteCounts(await scan(`<ul>${items.join("")}</ul>`))).toEqual({ bgOverlap: 1 });
  });

  it("counts another column as a place of its own", async () => {
    const rows = [0, 1].map((row) => `<tr>${cell(`a-${row}`)}${cell(`b-${row}`)}</tr>`);
    const page = await scan(`<table><tbody>${rows.join("")}</tbody></table>`);
    expect(incompleteCounts(page)).toEqual({ bgOverlap: 2 });
  });

  it("keeps apart nodes that differ only by an href or a generated id", async () => {
    // axe's short selectors for these are `a[href$="…"]` and `#_r_1_`.
    const page = await scan(`
      <header><a href="/one"><button id="_r_1_"></button></a></header>
      <nav><a href="/two"><button id="_r_2_"></button></a></nav>
      <main>
        <div><a href="/three"><button id="_r_3_"></button></a></div>
        <div><a href="/four"><button id="_r_4_"></button></a></div>
      </main>`);
    expect(incompleteCounts(page)).toEqual({ bgOverlap: 4 });
  });

  it("keeps different reasons apart", async () => {
    const first = await scan(`<main><button></button></main>`, "pseudoContent");
    const second = await scan(`<main><button></button></main>`, "bgOverlap");
    const nodes = [...first[0]!.nodes, ...second[0]!.nodes];
    expect(incompleteCounts([{ ...first[0]!, nodes }])).toEqual({ pseudoContent: 1, bgOverlap: 1 });
  });
});
