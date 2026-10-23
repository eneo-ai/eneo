import { describe, expect, it } from "vitest";
import { activeFacets, facetValueLabel, withFacet } from "./filterFacets";
import type { SharePointFilterColumn } from "./treeState";

const columns: SharePointFilterColumn[] = [
  { name: "Dokumenttyp", label: "Dokumenttyp", kind: "choice", choices: ["Rutin"] },
  { name: "Extern", label: "Extern publicering", kind: "boolean", choices: [] }
];

describe("filter facets", () => {
  it("lists chosen filters in column order and skips empty or unknown ones", () => {
    expect(
      activeFacets(columns, { Extern: "false", Dokumenttyp: "Rutin", Okänd: "x", Tom: "" }).map(
        (entry) => entry.column.name
      )
    ).toEqual(["Dokumenttyp", "Extern"]);
  });

  it("reads yes/no values for people", () => {
    const labels = { yes: "Ja", no: "Nej" };
    expect(facetValueLabel(columns[1], "true", labels)).toBe("Ja");
    expect(facetValueLabel(columns[1], "false", labels)).toBe("Nej");
    expect(facetValueLabel(columns[0], "Rutin", labels)).toBe("Rutin");
  });

  it("sets and clears one facet without touching the others", () => {
    expect(withFacet({ Extern: "true" }, "Dokumenttyp", "Rutin")).toEqual({
      Extern: "true",
      Dokumenttyp: "Rutin"
    });
    expect(withFacet({ Extern: "true", Dokumenttyp: "Rutin" }, "Extern", "")).toEqual({
      Dokumenttyp: "Rutin"
    });
  });
});
