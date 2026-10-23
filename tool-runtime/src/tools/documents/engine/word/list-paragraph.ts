// Runs inside sandbox children only. A list item that references a numbering instance by its
// id in the template's numbering part (see numbering.ts). The docx library resolves its own
// `numbering` option through the document it packs, which the patcher has no view of, so the
// reference is written onto the prepared XML instead. This is the one place that depends on
// the shape the library gives a paragraph (`{ "w:p": [{ "w:pPr": [...] }, ...] }`); the
// pack-and-read test in word.test.ts pins it, and the library version is pinned exactly.
import { Paragraph, type IContext, type IParagraphOptions, type IXmlableObject } from "docx";

/** Paragraph properties that precede `w:numPr` in the schema. */
const BEFORE_NUMBERING = new Set([
  "w:pStyle",
  "w:keepNext",
  "w:keepLines",
  "w:pageBreakBefore",
  "w:framePr",
  "w:widowControl",
]);

export class ListParagraph extends Paragraph {
  constructor(
    options: IParagraphOptions,
    private readonly list: { numId: number; level: number },
  ) {
    super(options);
  }

  override prepForXml(context: IContext): IXmlableObject | undefined {
    const xml = super.prepForXml(context);
    const paragraph = xml?.["w:p"];
    if (!Array.isArray(paragraph)) return xml;
    const numbering = {
      "w:numPr": [
        { "w:ilvl": { _attr: { "w:val": this.list.level } } },
        { "w:numId": { _attr: { "w:val": this.list.numId } } },
      ],
    };
    const holder = paragraph.find(
      (child): child is { "w:pPr": unknown } =>
        !!child && typeof child === "object" && "w:pPr" in child,
    );
    if (!holder) {
      paragraph.unshift({ "w:pPr": [numbering] });
      return xml;
    }
    const properties = holder["w:pPr"];
    if (!Array.isArray(properties)) {
      holder["w:pPr"] = [numbering];
      return xml;
    }
    let index = 0;
    while (
      index < properties.length &&
      BEFORE_NUMBERING.has(Object.keys(properties[index] as object)[0] ?? "")
    )
      index++;
    properties.splice(index, 0, numbering);
    return xml;
  }
}
