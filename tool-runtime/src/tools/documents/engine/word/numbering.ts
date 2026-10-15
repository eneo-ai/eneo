// Runs inside sandbox children only. Lists are the one thing the docx patcher cannot add to
// an existing document: a paragraph's `w:numPr` points at a numbering instance that must be
// defined in `word/numbering.xml`. This module adds those definitions to the template's
// part (creating it when the template has no lists) and hands back the instance ids the
// rendered paragraphs reference. Bullets share one instance; every numbered list gets its
// own, with a start override, so each list restarts where the Markdown says.
import type { TemplateInspection, Zip } from "./inspect";
import {
  attr,
  children,
  element,
  find,
  findAll,
  parseXml,
  rootElement,
  serializeXml,
  type Element,
} from "./ooxml";

const W_NAMESPACE = "http://schemas.openxmlformats.org/wordprocessingml/2006/main";
const NUMBERING_TYPE =
  "http://schemas.openxmlformats.org/officeDocument/2006/relationships/numbering";
const NUMBERING_CONTENT_TYPE =
  "application/vnd.openxmlformats-officedocument.wordprocessingml.numbering+xml";
const BULLETS = ["•", "◦", "▪", "•"];
export const LIST_LEVELS = 4;

/** What the rendered content needs: bullets at all, and the start number of each numbered list. */
export type ListNeeds = { bullets: boolean; numbered: number[] };
/** Numbering instance ids the paragraphs reference. */
export type ListIds = { bullet?: number; numbered: number[] };

function maxAttribute(nodes: Element[], name: string): number {
  return nodes.reduce((max, node) => Math.max(max, Number(attr(node, name) ?? -1)), -1);
}

/** Eneo's own list definition: four levels, bullets or decimal numbers. */
function abstractNum(id: number, ordered: boolean): Element {
  return element("w:abstractNum", { "w:abstractNumId": id }, [
    element("w:multiLevelType", { "w:val": "hybridMultilevel" }),
    ...Array.from({ length: LIST_LEVELS }, (_, level) =>
      element("w:lvl", { "w:ilvl": level }, [
        element("w:start", { "w:val": 1 }),
        element("w:numFmt", { "w:val": ordered ? "decimal" : "bullet" }),
        element("w:lvlText", { "w:val": ordered ? `%${level + 1}.` : BULLETS[level]! }),
        element("w:lvlJc", { "w:val": "left" }),
        element("w:pPr", {}, [element("w:ind", { "w:left": 720 * (level + 1), "w:hanging": 360 })]),
      ]),
    ),
  ]);
}

function instance(numId: number, abstractId: number, start?: number): Element {
  return element("w:num", { "w:numId": numId }, [
    element("w:abstractNumId", { "w:val": abstractId }),
    ...(start !== undefined
      ? [
          element("w:lvlOverride", { "w:ilvl": 0 }, [
            element("w:startOverride", { "w:val": start }),
          ]),
        ]
      : []),
  ]);
}

/** Appends a relationship and a content type for a numbering part the template lacked. */
async function registerNumberingPart(zip: Zip): Promise<void> {
  const relsName = "word/_rels/document.xml.rels";
  const rels = parseXml((await zip.file(relsName)?.async("string")) ?? "");
  const relationships = rootElement(rels);
  if (!findAll(relationships, "Relationship").some((r) => attr(r, "Type") === NUMBERING_TYPE)) {
    let id = 1;
    while (findAll(relationships, "Relationship").some((r) => attr(r, "Id") === `rIdEneo${id}`))
      id++;
    (relationships.elements ??= []).push(
      element("Relationship", {
        Id: `rIdEneo${id}`,
        Type: NUMBERING_TYPE,
        Target: "numbering.xml",
      }),
    );
    zip.file(relsName, serializeXml(rels));
  }
  const typesName = "[Content_Types].xml";
  const types = parseXml((await zip.file(typesName)?.async("string")) ?? "");
  const root = rootElement(types);
  if (!findAll(root, "Override").some((o) => attr(o, "PartName") === "/word/numbering.xml")) {
    (root.elements ??= []).push(
      element("Override", {
        PartName: "/word/numbering.xml",
        ContentType: NUMBERING_CONTENT_TYPE,
      }),
    );
    zip.file(typesName, serializeXml(types));
  }
}

/**
 * Adds the list definitions the content needs to the template's numbering part and returns
 * the instance ids. A template whose list styles link to numbering keeps its own glyphs and
 * indents: the instances point at those definitions; otherwise Eneo's definitions are added.
 */
export async function ensureListDefinitions(
  zip: Zip,
  inspection: Pick<TemplateInspection, "listNumbering">,
  needs: ListNeeds,
): Promise<ListIds> {
  if (!needs.bullets && !needs.numbered.length) return { numbered: [] };
  const name = "word/numbering.xml";
  const existing = await zip.file(name)?.async("string");
  const tree = parseXml(
    existing ??
      `<?xml version="1.0" encoding="UTF-8" standalone="yes"?><w:numbering xmlns:w="${W_NAMESPACE}"></w:numbering>`,
  );
  const numbering = rootElement(tree);
  numbering.elements ??= [];
  let nextAbstract = maxAttribute(findAll(numbering, "w:abstractNum"), "w:abstractNumId") + 1;
  let nextNum = Math.max(maxAttribute(findAll(numbering, "w:num"), "w:numId"), 0) + 1;
  const added: Element[] = [];
  const abstractFor = (ordered: boolean) => {
    const own = ordered ? inspection.listNumbering.number : inspection.listNumbering.bullet;
    if (own !== undefined) return own;
    const id = nextAbstract++;
    added.push(abstractNum(id, ordered));
    return id;
  };
  const ids: ListIds = { numbered: [] };
  const instances: Element[] = [];
  if (needs.bullets) {
    ids.bullet = nextNum++;
    instances.push(instance(ids.bullet, abstractFor(false)));
  }
  if (needs.numbered.length) {
    const abstractId = abstractFor(true);
    for (const start of needs.numbered) {
      const id = nextNum++;
      ids.numbered.push(id);
      instances.push(instance(id, abstractId, start));
    }
  }
  // Schema order: abstract definitions, then instances, then the cleanup marker if any.
  const firstNum = children(numbering).findIndex((child) => child.name === "w:num");
  numbering.elements.splice(firstNum < 0 ? numbering.elements.length : firstNum, 0, ...added);
  const cleanup = find(numbering, "w:numIdMacAtCleanup");
  const end = cleanup ? children(numbering).indexOf(cleanup) : numbering.elements.length;
  numbering.elements.splice(end, 0, ...instances);
  zip.file(name, serializeXml(tree));
  if (existing === undefined) await registerNumberingPart(zip);
  return ids;
}
